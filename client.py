import socket
import threading
import json
import os
from datetime import datetime

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


BROKER_HOST = "localhost"
BROKER_PORT = 1883

# CA do professor, usada para validar o certificado do broker.
# Quando o professor devolver o certificado/CA dele, salve aqui.
CERT_CA_PROFESSOR = os.path.join("certs", "ca_professor.crt")

# Arquivo local dos clientes com as chaves E2E dos tópicos.
# O broker não usa esse arquivo.
ARQUIVO_CHAVES_TOPICOS = os.path.join("certs", "chaves_topicos.json")


class ClienteWeb:
    def __init__(self):
        self.socket = None
        self.nome_cliente = ""
        self.conectado = False
        self.mensagens = []
        self.topicos = []
        self.topicos_desinscritos = []
        self.buffer = ""
        self.chave_sessao = None
        self.chaves_topicos = self.carregar_chaves_topicos()

    # ============================================================
    # Arquivo de chaves E2E dos tópicos
    # ============================================================

    def carregar_chaves_topicos(self):
        if not os.path.exists(ARQUIVO_CHAVES_TOPICOS):
            return {}

        try:
            with open(ARQUIVO_CHAVES_TOPICOS, "r", encoding="utf-8") as arquivo:
                return json.load(arquivo)

        except Exception:
            return {}

    def salvar_chaves_topicos(self):
        os.makedirs(os.path.dirname(ARQUIVO_CHAVES_TOPICOS), exist_ok=True)

        with open(ARQUIVO_CHAVES_TOPICOS, "w", encoding="utf-8") as arquivo:
            json.dump(
                self.chaves_topicos,
                arquivo,
                indent=4,
                ensure_ascii=False
            )

    def exportar_chave_topico(self, topico):
        return self.chaves_topicos.get(topico)

    def importar_chave_topico(self, topico, chave_topico):
        if not topico or not chave_topico:
            return False, "Tópico ou chave não informado."

        self.chaves_topicos[topico] = chave_topico
        self.salvar_chaves_topicos()

        return True, f"Chave do tópico '{topico}' importada com sucesso."

    # ============================================================
    # Comunicação TCP com JSON separado por \n
    # ============================================================

    def enviar_json(self, pacote):
        mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
        self.socket.sendall(mensagem.encode("utf-8"))

    def receber_json(self):
        while "\n" not in self.buffer:
            dados = self.socket.recv(4096)

            if not dados:
                return None

            self.buffer += dados.decode("utf-8")

        linha, self.buffer = self.buffer.split("\n", 1)

        if not linha.strip():
            return self.receber_json()

        return json.loads(linha)

    # ============================================================
    # Envelopamento digital próprio com AES
    # ============================================================

    def enviar_criptografado(self, pacote):
        envelope = criptografar_json(self.chave_sessao, pacote)
        envelope["tipo"] = "envelope"

        self.enviar_json(envelope)

    def receber_criptografado(self):
        envelope = self.receber_json()

        if envelope is None:
            return None

        if envelope.get("tipo") == "erro":
            return envelope

        if envelope.get("tipo") != "envelope":
            raise ValueError("Pacote recebido não está envelopado/criptografado.")

        return descriptografar_json(self.chave_sessao, envelope)

    # ============================================================
    # Handshake próprio, sem TLS
    # ============================================================

    def realizar_handshake(self):
        pacote_broker = self.receber_json()

        if pacote_broker is None:
            return False, "Broker desconectou durante o handshake."

        if pacote_broker.get("tipo") != "handshake_broker":
            return False, "Handshake inválido. Broker não enviou o pacote esperado."

        certificado_broker_pem = pacote_broker.get("certificado_broker")
        desafio_broker_b64 = pacote_broker.get("desafio")

        if not certificado_broker_pem:
            return False, "Broker não enviou certificado."

        if not desafio_broker_b64:
            return False, "Broker não enviou desafio."

        if not os.path.exists(CERT_CA_PROFESSOR):
            return False, f"CA do professor não encontrada: {CERT_CA_PROFESSOR}"

        certificado_broker = carregar_certificado_pem_texto(
            certificado_broker_pem
        )

        certificado_ca_professor = carregar_certificado(
            CERT_CA_PROFESSOR
        )

        broker_valido = verificar_assinatura_certificado(
            certificado_broker,
            certificado_ca_professor
        )

        if not broker_valido:
            return False, "Certificado do broker não foi assinado pela CA do professor."

        cn_broker = obter_common_name_certificado(certificado_broker)

        if cn_broker != "ServidorBroker":
            return False, f"Certificado do broker possui CN inesperado: {cn_broker}"

        cert_cliente = os.path.join(
            "certs",
            "clientes",
            self.nome_cliente,
            f"{self.nome_cliente}.crt"
        )

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

        certificado_cliente_pem = certificado_para_pem(cert_cliente)
        chave_privada_cliente = carregar_chave_privada(chave_cliente)

        self.chave_sessao = gerar_chave_sessao()

        chave_publica_broker = certificado_broker.public_key()

        chave_sessao_criptografada = criptografar_com_chave_publica(
            chave_publica_broker,
            self.chave_sessao
        )

        chave_sessao_criptografada_b64 = b64_encode(
            chave_sessao_criptografada
        )

        dados_assinados = (
            f"{self.nome_cliente}|{desafio_broker_b64}|{chave_sessao_criptografada_b64}"
        ).encode("utf-8")

        assinatura = assinar_dados(
            chave_privada_cliente,
            dados_assinados
        )

        assinatura_b64 = b64_encode(assinatura)

        self.enviar_json({
            "tipo": "handshake_cliente",
            "id": self.nome_cliente,
            "certificado_cliente": certificado_cliente_pem,
            "chave_sessao": chave_sessao_criptografada_b64,
            "assinatura": assinatura_b64
        })

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
        try:
            self.nome_cliente = nome_cliente.strip()
            self.buffer = ""
            self.chave_sessao = None

            if not self.nome_cliente:
                return False, "Nome do cliente não informado."

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((BROKER_HOST, BROKER_PORT))

            sucesso, mensagem = self.realizar_handshake()

            if not sucesso:
                self.conectado = False

                try:
                    self.socket.close()
                except Exception:
                    pass

                return False, mensagem

            self.conectado = True

            thread = threading.Thread(target=self.receber_mensagens)
            thread.daemon = True
            thread.start()

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
        if not self.conectado:
            raise ConnectionError("Cliente não está conectado.")

        self.enviar_criptografado(pacote)

    def criar_topico(self, topico):
        if not self.conectado:
            return False, "Cliente não está conectado."

        if not topico:
            return False, "Nome do tópico não informado."

        if topico not in self.chaves_topicos:
            from utils.crypto_utils import gerar_chave_topico

            self.chaves_topicos[topico] = gerar_chave_topico()
            self.salvar_chaves_topicos()

        self.enviar({
            "tipo": "criar_topico",
            "id": self.nome_cliente,
            "topico": topico
        })

        return True, f"Tópico '{topico}' criado. Chave E2E gerada localmente."

    def inscrever(self, topico):
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "inscrever",
            "id": self.nome_cliente,
            "topico": topico
        })

        if topico not in self.chaves_topicos:
            self.mensagens.append(
                f"Sistema: Você entrou no tópico '{topico}', mas ainda precisa da chave E2E para ler as mensagens."
            )

        return True, f"Solicitação de inscrição no tópico '{topico}' enviada."

    def desinscrever(self, topico):
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "desinscrever",
            "id": self.nome_cliente,
            "topico": topico
        })

        return True, f"Solicitação para sair do tópico '{topico}' enviada."

    def publicar(self, topico, mensagem):
        if not self.conectado:
            return False, "Cliente não está conectado."

        if topico not in self.chaves_topicos:
            return False, (
                f"Você não possui a chave E2E do tópico '{topico}'. "
                f"Importe a chave antes de publicar."
            )

        payload_criptografado = criptografar_payload_ponta_a_ponta(
            self.chaves_topicos[topico],
            mensagem
        )

        self.enviar({
            "tipo": "publicar",
            "id": self.nome_cliente,
            "topico": topico,
            "payload_criptografado": payload_criptografado
        })

        return True, f"Mensagem criptografada enviada para o tópico '{topico}'."

    def listar_topicos(self):
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "listar_topicos",
            "id": self.nome_cliente
        })

        return True, "Solicitação de listagem de tópicos enviada."

    def desconectar(self):
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
        while self.conectado:
            try:
                pacote = self.receber_criptografado()

                if pacote is None:
                    break

                tipo = pacote.get("tipo")

                if tipo == "mensagem":
                    topico = pacote.get("topico")
                    remetente = pacote.get("remetente")
                    payload_criptografado = pacote.get("payload_criptografado")
                    hora = datetime.now().strftime("%H:%M")

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
                    else:
                        mensagem = (
                            "[payload criptografado recebido, "
                            "mas este cliente não possui a chave E2E do tópico]"
                        )

                    texto = f"[{topico}] {remetente}: {mensagem} [{hora}]"
                    self.mensagens.append(texto)

                elif tipo == "resposta":
                    mensagem = pacote.get("mensagem")
                    hora = datetime.now().strftime("%H:%M")

                    texto = f"Sistema: {mensagem} [{hora}]"
                    self.mensagens.append(texto)

                elif tipo == "topicos":
                    self.topicos = pacote.get("topicos", [])

                elif tipo == "desinscrito":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")
                    hora = datetime.now().strftime("%H:%M")

                    self.topicos_desinscritos.append(topico)
                    self.mensagens.append(f"Sistema: {mensagem} [{hora}]")

                elif tipo == "erro":
                    mensagem = pacote.get("mensagem")
                    self.mensagens.append(f"Erro: {mensagem}")

            except Exception as e:
                if self.conectado:
                    self.mensagens.append(f"Erro ao receber mensagem: {e}")
                break

        self.conectado = False