import socket
import threading
import json
import os
from datetime import datetime

# Importa as funções criptográficas do arquivo utils/crypto_utils.py
from utils.crypto_utils import (
    b64_encode,
    certificado_para_pem,
    carregar_certificado,
    carregar_certificado_pem_texto,
    carregar_chave_privada,
    verificar_assinatura_certificado,
    obter_common_name_certificado,
    gerar_chave_sessao,
    criptografar_com_chave_publica,
    assinar_dados,
    criptografar_json,
    descriptografar_json,
    criptografar_payload_ponta_a_ponta,
    descriptografar_payload_ponta_a_ponta
)


# ============================================================
# Configurações principais do cliente
# ============================================================

# Endereço do broker.
# localhost significa que o broker está rodando na mesma máquina.
BROKER_HOST = "localhost"

# Porta usada pelo broker.
# A porta 1883 é a porta padrão do MQTT.
BROKER_PORT = 1883

# Certificado da CA do professor.
# O cliente usa esse arquivo para validar se o certificado do broker
# foi realmente assinado por uma autoridade confiável.
CERT_CA_PROFESSOR = os.path.join("certs", "ca_professor.crt")

# Arquivo local onde ficam as chaves E2E dos tópicos.
# Essas chaves são usadas para criptografia ponta a ponta.
# O broker não acessa esse arquivo.
ARQUIVO_CHAVES_TOPICOS = os.path.join("certs", "chaves_topicos.json")


class ClienteWeb:
    """
    Classe que representa o cliente do sistema.

    Ela é usada pelo main.py, que é a interface em Streamlit.
    Aqui ficam:
    - conexão TCP;
    - handshake próprio;
    - validação do certificado do broker;
    - envio de comandos;
    - recebimento de mensagens;
    - criptografia ponta a ponta.
    """

    def __init__(self):
        # Socket TCP usado para conversar com o broker.
        self.socket = None

        # Nome do cliente, por exemplo: cliente1 ou cliente2.
        self.nome_cliente = ""

        # Indica se o cliente está conectado ao broker.
        self.conectado = False

        # Lista onde ficam mensagens recebidas.
        # O main.py lê essa lista para exibir na tela.
        self.mensagens = []

        # Lista de tópicos recebida do broker.
        self.topicos = []

        # Lista de tópicos dos quais o cliente saiu.
        self.topicos_desinscritos = []

        # Buffer usado para receber dados do TCP até formar um pacote completo.
        self.buffer = ""

        # Chave de sessão AES criada no handshake.
        # Ela protege a comunicação entre cliente e broker.
        self.chave_sessao = None

        # Dicionário com as chaves E2E dos tópicos.
        # Exemplo:
        # {
        #     "Avisos": "chave_em_base64"
        # }
        self.chaves_topicos = self.carregar_chaves_topicos()

    # ============================================================
    # Arquivo de chaves E2E dos tópicos
    # ============================================================

    def carregar_chaves_topicos(self):
        """
        Carrega as chaves E2E dos tópicos do arquivo chaves_topicos.json.

        Essas chaves permitem criptografar e descriptografar o payload
        das mensagens dos tópicos.
        """
        if not os.path.exists(ARQUIVO_CHAVES_TOPICOS):
            return {}

        try:
            with open(ARQUIVO_CHAVES_TOPICOS, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)

        except Exception:
            return {}

    def salvar_chaves_topicos(self):
        """
        Salva as chaves E2E dos tópicos em arquivo JSON.

        O broker não usa esse arquivo. Ele fica apenas no lado do cliente.
        """
        os.makedirs(os.path.dirname(ARQUIVO_CHAVES_TOPICOS), exist_ok=True)

        with open(ARQUIVO_CHAVES_TOPICOS, "w", encoding="utf-8") as arquivo:
            json.dump(
                self.chaves_topicos,
                arquivo,
                indent=4,
                ensure_ascii=False
            )

    def exportar_chave_topico(self, topico):
        """
        Retorna a chave E2E de um tópico.

        Essa função é usada pela interface para mostrar a chave
        e permitir compartilhar com outro cliente autorizado.
        """
        return self.chaves_topicos.get(topico)

    def importar_chave_topico(self, topico, chave_topico):
        """
        Importa uma chave E2E para um tópico.

        Isso permite que o cliente consiga ler mensagens criptografadas
        daquele tópico.
        """
        if not topico or not chave_topico:
            return False, "Tópico ou chave não informado."

        self.chaves_topicos[topico] = chave_topico
        self.salvar_chaves_topicos()

        return True, f"Chave do tópico '{topico}' importada com sucesso."

    # ============================================================
    # Comunicação TCP com JSON separado por \n
    # ============================================================

    def enviar_json(self, pacote):
        """
        Envia um pacote JSON pelo TCP.

        Como TCP trabalha com fluxo de bytes, usamos '\n'
        para indicar onde um pacote termina.
        """
        mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
        self.socket.sendall(mensagem.encode("utf-8"))

    def receber_json(self):
        """
        Recebe um pacote JSON pelo TCP.

        O TCP pode entregar dados quebrados ou agrupados.
        Por isso, usamos um buffer até encontrar '\n'.
        """
        while "\n" not in self.buffer:
            dados = self.socket.recv(4096)

            # Se não veio dado, significa que a conexão foi encerrada.
            if not dados:
                return None

            self.buffer += dados.decode("utf-8")

        # Separa uma linha completa do restante do buffer.
        linha, self.buffer = self.buffer.split("\n", 1)

        # Ignora linhas vazias.
        if not linha.strip():
            return self.receber_json()

        # Converte o JSON recebido em dicionário Python.
        return json.loads(linha)

    # ============================================================
    # Envelopamento digital próprio com AES
    # ============================================================

    def enviar_criptografado(self, pacote):
        """
        Criptografa um pacote com a chave de sessão AES
        e envia para o broker.

        Essa é a camada de envelopamento digital próprio.
        Não usamos TLS.
        """
        envelope = criptografar_json(self.chave_sessao, pacote)

        # Identifica que o pacote é um envelope criptografado.
        envelope["tipo"] = "envelope"

        self.enviar_json(envelope)

    def receber_criptografado(self):
        """
        Recebe um envelope criptografado e descriptografa.

        Depois do handshake, a comunicação normal com o broker
        passa por essa função.
        """
        envelope = self.receber_json()

        if envelope is None:
            return None

        # Durante falhas de handshake, o broker pode mandar erro em texto aberto.
        if envelope.get("tipo") == "erro":
            return envelope

        # Depois do handshake, o esperado é receber pacotes envelopados.
        if envelope.get("tipo") != "envelope":
            raise ValueError("Pacote recebido não está envelopado/criptografado.")

        # Descriptografa o envelope usando a chave de sessão AES.
        return descriptografar_json(self.chave_sessao, envelope)

    # ============================================================
    # Handshake próprio, sem TLS
    # ============================================================

    def realizar_handshake(self):
        """
        Realiza o handshake próprio com o broker.

        O handshake serve para:
        - validar o certificado do broker;
        - gerar uma chave de sessão AES;
        - enviar essa chave de forma segura ao broker;
        - autenticar o cliente com certificado e assinatura.

        Fluxo:
        1. Cliente recebe certificado e desafio do broker.
        2. Cliente valida o certificado do broker com a CA do professor.
        3. Cliente gera uma chave de sessão AES.
        4. Cliente criptografa essa chave com a chave pública do broker.
        5. Cliente assina os dados do handshake com sua chave privada.
        6. Cliente envia certificado, chave criptografada e assinatura.
        7. Broker valida e responde usando a chave de sessão.
        """

        # Recebe o primeiro pacote enviado pelo broker.
        pacote_broker = self.receber_json()

        if pacote_broker is None:
            return False, "Broker desconectou durante o handshake."

        if pacote_broker.get("tipo") != "handshake_broker":
            return False, "Handshake inválido. Broker não enviou o pacote esperado."

        # Dados enviados pelo broker.
        certificado_broker_pem = pacote_broker.get("certificado_broker")
        desafio_broker_b64 = pacote_broker.get("desafio")

        if not certificado_broker_pem:
            return False, "Broker não enviou certificado."

        if not desafio_broker_b64:
            return False, "Broker não enviou desafio."

        # Verifica se a CA do professor existe localmente.
        if not os.path.exists(CERT_CA_PROFESSOR):
            return False, f"CA do professor não encontrada: {CERT_CA_PROFESSOR}"

        # Converte o certificado do broker, recebido em texto PEM, em objeto.
        certificado_broker = carregar_certificado_pem_texto(
            certificado_broker_pem
        )

        # Carrega o certificado da CA do professor.
        certificado_ca_professor = carregar_certificado(
            CERT_CA_PROFESSOR
        )

        # Verifica se o certificado do broker foi assinado pela CA do professor.
        broker_valido = verificar_assinatura_certificado(
            certificado_broker,
            certificado_ca_professor
        )

        if not broker_valido:
            return False, "Certificado do broker não foi assinado pela CA do professor."

        # Pega o CN do certificado do broker.
        cn_broker = obter_common_name_certificado(certificado_broker)

        # Confere se o certificado recebido pertence ao broker esperado.
        if cn_broker != "ServidorBroker":
            return False, f"Certificado do broker possui CN inesperado: {cn_broker}"

        # Caminho do certificado do cliente.
        # O nome digitado na interface precisa ser igual ao nome da pasta.
        cert_cliente = os.path.join(
            "certs",
            "clientes",
            self.nome_cliente,
            f"{self.nome_cliente}.crt"
        )

        # Caminho da chave privada do cliente.
        chave_cliente = os.path.join(
            "certs",
            "clientes",
            self.nome_cliente,
            f"{self.nome_cliente}.key"
        )

        if not os.path.exists(cert_cliente):
            return False, f"Certificado do cliente não encontrado: {cert_cliente}"

        if not os.path.exists(chave_cliente):
            return False, f"Chave privada do cliente não encontrada: {chave_cliente}"

        # Lê o certificado do cliente como texto PEM para enviar ao broker.
        certificado_cliente_pem = certificado_para_pem(cert_cliente)

        # Carrega a chave privada do cliente para assinar os dados do handshake.
        chave_privada_cliente = carregar_chave_privada(chave_cliente)

        # Gera a chave de sessão AES.
        # Essa chave será usada na comunicação cliente-broker depois do handshake.
        self.chave_sessao = gerar_chave_sessao()

        # Obtém a chave pública do broker a partir do certificado dele.
        chave_publica_broker = certificado_broker.public_key()

        # Criptografa a chave de sessão com a chave pública do broker.
        # Só o broker conseguirá abrir usando a chave privada dele.
        chave_sessao_criptografada = criptografar_com_chave_publica(
            chave_publica_broker,
            self.chave_sessao
        )

        # Converte a chave criptografada para Base64 para caber no JSON.
        chave_sessao_criptografada_b64 = b64_encode(
            chave_sessao_criptografada
        )

        # Monta os dados que serão assinados pelo cliente.
        # A assinatura prova que o cliente possui a chave privada.
        dados_assinados = (
            f"{self.nome_cliente}|{desafio_broker_b64}|{chave_sessao_criptografada_b64}"
        ).encode("utf-8")

        # Assina os dados com a chave privada do cliente.
        assinatura = assinar_dados(
            chave_privada_cliente,
            dados_assinados
        )

        # Converte a assinatura para Base64 para enviar em JSON.
        assinatura_b64 = b64_encode(assinatura)

        # Envia ao broker os dados do handshake do cliente.
        self.enviar_json({
            "tipo": "handshake_cliente",
            "id": self.nome_cliente,
            "certificado_cliente": certificado_cliente_pem,
            "chave_sessao": chave_sessao_criptografada_b64,
            "assinatura": assinatura_b64
        })

        # A resposta do broker já vem criptografada com a chave de sessão.
        resposta = self.receber_criptografado()

        if resposta is None:
            return False, "Broker desconectou após o handshake."

        if resposta.get("tipo") == "erro":
            return False, resposta.get("mensagem", "Erro no handshake.")

        return True, resposta.get(
            "mensagem",
            "Handshake realizado com sucesso."
        )

    # ============================================================
    # Conexão
    # ============================================================

    def conectar(self, nome_cliente):
        """
        Conecta o cliente ao broker.

        Essa função:
        - salva o nome do cliente;
        - abre uma conexão TCP;
        - executa o handshake;
        - inicia uma thread para receber mensagens;
        - solicita mensagens pendentes.
        """
        try:
            self.nome_cliente = nome_cliente.strip()
            self.buffer = ""
            self.chave_sessao = None

            if not self.nome_cliente:
                return False, "Nome do cliente não informado."

            # Cria o socket TCP.
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            # Conecta ao broker.
            self.socket.connect((BROKER_HOST, BROKER_PORT))

            # Executa o handshake próprio.
            sucesso, mensagem = self.realizar_handshake()

            if not sucesso:
                self.conectado = False

                try:
                    self.socket.close()
                except Exception:
                    pass

                return False, mensagem

            # Marca o cliente como conectado.
            self.conectado = True

            # Cria uma thread para receber mensagens sem travar a interface.
            thread = threading.Thread(target=self.receber_mensagens)
            thread.daemon = True
            thread.start()

            # Solicita mensagens pendentes guardadas no broker.
            self.enviar({
                "tipo": "solicitar_pendentes",
                "id": self.nome_cliente
            })

            return True, mensagem

        except Exception as e:
            self.conectado = False

            try:
                if self.socket:
                    self.socket.close()
            except Exception:
                pass

            return False, f"Erro ao conectar/autenticar: {e}"

    # ============================================================
    # Envio de comandos ao broker
    # ============================================================

    def enviar(self, pacote):
        """
        Envia um pacote criptografado ao broker.

        Só pode ser usado depois que o cliente já está conectado
        e a chave de sessão foi criada.
        """
        if not self.conectado:
            raise ConnectionError("Cliente não está conectado.")

        self.enviar_criptografado(pacote)

    def criar_topico(self, topico):
        """
        Solicita a criação de um tópico ao broker.

        Também gera uma chave E2E local para esse tópico.
        Essa chave não é enviada ao broker.
        """
        if not self.conectado:
            return False, "Cliente não está conectado."

        if not topico:
            return False, "Nome do tópico não informado."

        # Se ainda não existe chave E2E para esse tópico, gera uma.
        if topico not in self.chaves_topicos:
            from utils.crypto_utils import gerar_chave_topico

            self.chaves_topicos[topico] = gerar_chave_topico()
            self.salvar_chaves_topicos()

        # Envia o comando de criação do tópico para o broker.
        self.enviar({
            "tipo": "criar_topico",
            "id": self.nome_cliente,
            "topico": topico
        })

        return True, f"Tópico '{topico}' criado. Chave E2E gerada localmente."

    def inscrever(self, topico):
        """
        Solicita inscrição em um tópico.

        Entrar no tópico não significa automaticamente conseguir ler as mensagens.
        Para ler o payload, o cliente precisa ter a chave E2E do tópico.
        """
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "inscrever",
            "id": self.nome_cliente,
            "topico": topico
        })

        # Caso o cliente não tenha a chave E2E, avisa na tela.
        if topico not in self.chaves_topicos:
            self.mensagens.append(
                f"Sistema: Você entrou no tópico '{topico}', mas ainda precisa da chave E2E para ler as mensagens."
            )

        return True, f"Solicitação de inscrição no tópico '{topico}' enviada."

    def desinscrever(self, topico):
        """
        Solicita saída de um tópico.
        """
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "desinscrever",
            "id": self.nome_cliente,
            "topico": topico
        })

        return True, f"Solicitação para sair do tópico '{topico}' enviada."

    def publicar(self, topico, mensagem):
        """
        Publica uma mensagem em um tópico.

        Antes de enviar ao broker, o payload é criptografado com a chave E2E.
        Assim o broker consegue encaminhar, mas não consegue ler a mensagem.
        """
        if not self.conectado:
            return False, "Cliente não está conectado."

        # Sem a chave E2E, o cliente não pode publicar naquele tópico.
        if topico not in self.chaves_topicos:
            return False, (
                f"Você não possui a chave E2E do tópico '{topico}'. "
                f"Importe a chave antes de publicar."
            )

        # Criptografa o conteúdo da mensagem com a chave E2E do tópico.
        payload_criptografado = criptografar_payload_ponta_a_ponta(
            self.chaves_topicos[topico],
            mensagem
        )

        # Envia para o broker apenas o payload criptografado.
        self.enviar({
            "tipo": "publicar",
            "id": self.nome_cliente,
            "topico": topico,
            "payload_criptografado": payload_criptografado
        })

        return True, f"Mensagem criptografada enviada para o tópico '{topico}'."

    def listar_topicos(self):
        """
        Solicita ao broker a lista de tópicos disponíveis.
        """
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "listar_topicos",
            "id": self.nome_cliente
        })

        return True, "Solicitação de listagem de tópicos enviada."

    def desconectar(self):
        """
        Desconecta o cliente do broker.
        """
        self.conectado = False

        try:
            if self.socket:
                self.socket.close()
        except Exception:
            pass

    # ============================================================
    # Recebimento de mensagens
    # ============================================================

    def receber_mensagens(self):
        """
        Fica recebendo mensagens do broker em segundo plano.

        Essa função roda em uma thread separada.
        Quando recebe uma mensagem de tópico, tenta descriptografar
        o payload usando a chave E2E do tópico.
        """
        while self.conectado:
            try:
                pacote = self.receber_criptografado()

                if pacote is None:
                    break

                tipo = pacote.get("tipo")

                # Mensagem publicada em um tópico.
                if tipo == "mensagem":
                    topico = pacote.get("topico")
                    remetente = pacote.get("remetente")
                    payload_criptografado = pacote.get("payload_criptografado")
                    hora = datetime.now().strftime("%H:%M")

                    # Se o cliente tem a chave E2E do tópico, tenta ler a mensagem.
                    if topico in self.chaves_topicos:
                        try:
                            mensagem = descriptografar_payload_ponta_a_ponta(
                                self.chaves_topicos[topico],
                                payload_criptografado
                            )

                        except Exception:
                            mensagem = (
                                "[payload criptografado recebido, "
                                "mas não foi possível descriptografar]"
                            )

                    # Se não tem a chave E2E, recebe o pacote, mas não lê o conteúdo.
                    else:
                        mensagem = (
                            "[payload criptografado recebido, "
                            "mas este cliente não possui a chave E2E do tópico]"
                        )

                    # Guarda a mensagem para a interface exibir.
                    texto = f"[{topico}] {remetente}: {mensagem} [{hora}]"
                    self.mensagens.append(texto)

                # Resposta comum do broker.
                elif tipo == "resposta":
                    mensagem = pacote.get("mensagem")
                    hora = datetime.now().strftime("%H:%M")

                    texto = f"Sistema: {mensagem} [{hora}]"
                    self.mensagens.append(texto)

                # Atualiza a lista de tópicos recebida do broker.
                elif tipo == "topicos":
                    self.topicos = pacote.get("topicos", [])

                # Confirmação de que o cliente saiu de um tópico.
                elif tipo == "desinscrito":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")
                    hora = datetime.now().strftime("%H:%M")

                    self.topicos_desinscritos.append(topico)
                    self.mensagens.append(f"Sistema: {mensagem} [{hora}]")

                # Erro enviado pelo broker.
                elif tipo == "erro":
                    mensagem = pacote.get("mensagem")
                    self.mensagens.append(f"Erro: {mensagem}")

            except Exception as e:
                if self.conectado:
                    self.mensagens.append(f"Erro ao receber mensagem: {e}")
                break

        # Quando sai do loop, marca como desconectado.
        self.conectado = False