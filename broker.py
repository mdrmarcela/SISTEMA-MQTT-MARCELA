import socket
import threading
import json
import os
import secrets

# Importa funções auxiliares de criptografia do arquivo utils/crypto_utils.py
from utils.crypto_utils import (
    b64_encode,
    b64_decode,
    certificado_para_pem,
    carregar_certificado,
    carregar_certificado_pem_texto,
    carregar_chave_privada,
    verificar_assinatura_certificado,
    obter_common_name_certificado,
    obter_fingerprint_sha256,
    descriptografar_com_chave_privada,
    verificar_assinatura_dados,
    criptografar_json,
    descriptografar_json
)

# ============================================================
# Configurações principais do broker
# ============================================================

# Endereço onde o broker vai escutar conexões.
# 0.0.0.0 permite aceitar conexões da própria máquina e de outros computadores da rede.
BROKER_HOST = "0.0.0.0"

# Porta usada pelo broker. A porta 1883 é a porta padrão do MQTT.
BROKER_PORT = 1883

# Certificado público do broker/servidor.
# Esse certificado foi assinado pelo professor.
CERT_SERVIDOR = os.path.join("certs", "servidor", "marcela.crt")

# Chave privada do broker.
# Essa chave nunca deve ser compartilhada.
CHAVE_SERVIDOR = os.path.join("certs", "servidor", "servidor.key")

# Certificado da autoridade que assinou os certificados dos clientes.
# O broker usa esse certificado para validar se o certificado do cliente é confiável.
CA_CLIENTES = os.path.join("certs", "ca_clientes.crt")

# Arquivo JSON que contém os clientes autorizados e seus fingerprints.
# Isso evita autenticar clientes apenas pelo CN do certificado.
ARQUIVO_CLIENTES_AUTORIZADOS = os.path.join(
    "certs",
    "clientes_autorizados.json"
)

# ============================================================
# Estruturas em memória do broker
# ============================================================

# Guarda os clientes conectados no momento.
# Exemplo:
# {
#     "cliente1": {
#         "conn": socket_do_cliente,
#         "chave_sessao": chave_AES_da_conexao
#     }
# }
clientes_conectados = {}

# Guarda os tópicos existentes no broker.
# Como é um set, não permite tópicos duplicados.
topicos = set()

# Guarda quais clientes estão inscritos em cada tópico.
# Exemplo:
# {
#     "redes": {"cliente1", "cliente2"}
# }
subscricoes = {}

# Buffer de mensagens pendentes.
# Guarda mensagens que ainda não foram entregues para clientes offline.
# Exemplo:
# {
#     "redes": [
#         {
#             "pacote": pacote_da_mensagem,
#             "pendentes": {"cliente2"}
#         }
#     ]
# }
mensagens_topico = {}

# Lock usado para evitar conflitos quando várias threads acessam
# as mesmas estruturas ao mesmo tempo.
lock = threading.Lock()


# ============================================================
# Comunicação TCP com pacotes JSON separados por \n
# ============================================================

def enviar_json(conn, pacote):
    """
    Envia um pacote JSON pela conexão TCP.

    O TCP trabalha com fluxo de bytes, e não com mensagens separadas.
    Por isso, adicionamos '\n' no final para marcar onde cada pacote termina.
    """
    mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
    conn.sendall(mensagem.encode("utf-8"))


def receber_json(conn, buffer):
    """
    Recebe um pacote JSON pela conexão TCP.

    Como o TCP pode entregar uma mensagem em partes ou várias mensagens juntas,
    usamos um buffer até encontrar o caractere '\n', que indica o fim do pacote.
    """
    while "\n" not in buffer:
        dados = conn.recv(4096)

        # Se não chegou nenhum dado, significa que o cliente desconectou.
        if not dados:
            return None, buffer

        buffer += dados.decode("utf-8")

    # Separa uma mensagem completa do restante do buffer.
    linha, buffer = buffer.split("\n", 1)

    # Ignora linhas vazias.
    if not linha.strip():
        return receber_json(conn, buffer)

    # Converte o texto JSON recebido em um dicionário Python.
    return json.loads(linha), buffer


# ============================================================
# Envelopamento digital próprio
# ============================================================

def enviar_criptografado(conn, chave_sessao, pacote):
    """
    Criptografa um pacote usando a chave de sessão AES e envia pela conexão TCP.

    Essa função representa o envelopamento digital próprio do projeto.
    Não é TLS/SSL. É uma camada de segurança implementada manualmente.
    """
    envelope = criptografar_json(chave_sessao, pacote)

    # Identifica que o pacote enviado é um envelope criptografado.
    envelope["tipo"] = "envelope"

    enviar_json(conn, envelope)


def receber_criptografado(conn, chave_sessao, buffer):
    """
    Recebe um envelope criptografado, descriptografa e retorna o pacote original.

    Depois do handshake, toda comunicação entre cliente e broker passa por aqui.
    """
    envelope, buffer = receber_json(conn, buffer)

    if envelope is None:
        return None, buffer

    # Depois do handshake, o broker espera receber apenas pacotes envelopados.
    if envelope.get("tipo") != "envelope":
        raise ValueError("Pacote recebido não está envelopado/criptografado.")

    # Descriptografa o pacote usando a chave de sessão AES.
    pacote = descriptografar_json(chave_sessao, envelope)

    return pacote, buffer


# ============================================================
# Clientes autorizados
# ============================================================

def normalizar_fingerprint(fingerprint):
    """
    Normaliza o fingerprint para comparação.

    Alguns fingerprints podem aparecer com ':' entre os bytes.
    Essa função remove ':' e deixa tudo em minúsculo.
    """
    if not fingerprint:
        return ""

    return fingerprint.replace(":", "").strip().lower()


def carregar_clientes_autorizados():
    """
    Carrega o arquivo JSON de clientes autorizados.

    Esse arquivo contém o fingerprint SHA-256 de cada cliente permitido.
    """
    if not os.path.exists(ARQUIVO_CLIENTES_AUTORIZADOS):
        print(f"[!] Arquivo não encontrado: {ARQUIVO_CLIENTES_AUTORIZADOS}")
        return {}

    try:
        with open(ARQUIVO_CLIENTES_AUTORIZADOS, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)

    except Exception as e:
        print(f"[!] Erro ao carregar clientes autorizados: {e}")
        return {}


# ============================================================
# Handshake próprio
# ============================================================

def realizar_handshake(conn):
    """
    Faz o handshake próprio do projeto, sem usar TLS.

    O handshake é a etapa inicial da conexão. Ele serve para:
    - autenticar o broker;
    - autenticar o cliente;
    - provar que o cliente possui a chave privada do certificado;
    - criar uma chave de sessão AES para criptografar a comunicação.

    Fluxo:
    1. Broker envia seu certificado e um desafio aleatório.
    2. Cliente valida o certificado do broker usando a CA do professor.
    3. Cliente gera uma chave de sessão AES.
    4. Cliente criptografa a chave de sessão com a chave pública do broker.
    5. Cliente envia seu certificado, a chave de sessão criptografada e uma assinatura.
    6. Broker valida o certificado do cliente.
    7. Broker confere o fingerprint do cliente na lista de autorizados.
    8. Broker verifica a assinatura do desafio.
    9. Broker descriptografa a chave de sessão usando sua chave privada.
    """

    buffer = ""

    # Carrega o certificado público do broker em formato PEM.
    certificado_broker_pem = certificado_para_pem(CERT_SERVIDOR)

    # Carrega a chave privada do broker.
    # Ela será usada para descriptografar a chave de sessão enviada pelo cliente.
    chave_privada_broker = carregar_chave_privada(CHAVE_SERVIDOR)

    # Carrega a CA que valida os certificados dos clientes.
    certificado_ca_clientes = carregar_certificado(CA_CLIENTES)

    # Gera um desafio aleatório.
    # O cliente deverá assinar esse desafio para provar que possui sua chave privada.
    desafio_broker = secrets.token_bytes(32)
    desafio_broker_b64 = b64_encode(desafio_broker)

    # Envia ao cliente o certificado do broker e o desafio.
    enviar_json(conn, {
        "tipo": "handshake_broker",
        "certificado_broker": certificado_broker_pem,
        "desafio": desafio_broker_b64
    })

    # Recebe a resposta inicial do cliente.
    pacote_cliente, buffer = receber_json(conn, buffer)

    if pacote_cliente is None:
        return None, None, buffer, "Cliente desconectou durante o handshake."

    if pacote_cliente.get("tipo") != "handshake_cliente":
        return None, None, buffer, "Handshake inválido. Pacote inicial do cliente incorreto."

    # Dados enviados pelo cliente durante o handshake.
    id_cliente = pacote_cliente.get("id")
    certificado_cliente_pem = pacote_cliente.get("certificado_cliente")
    chave_sessao_criptografada_b64 = pacote_cliente.get("chave_sessao")
    assinatura_b64 = pacote_cliente.get("assinatura")

    # Verifica se todos os campos obrigatórios foram enviados.
    if not id_cliente:
        return None, None, buffer, "Cliente não informou identificação."

    if not certificado_cliente_pem:
        return None, None, buffer, "Cliente não enviou certificado."

    if not chave_sessao_criptografada_b64:
        return None, None, buffer, "Cliente não enviou chave de sessão criptografada."

    if not assinatura_b64:
        return None, None, buffer, "Cliente não enviou assinatura do desafio."

    # Converte o certificado do cliente, que veio em texto PEM, para objeto.
    certificado_cliente = carregar_certificado_pem_texto(certificado_cliente_pem)

    # Verifica se o certificado do cliente foi assinado por uma CA confiável.
    certificado_valido = verificar_assinatura_certificado(
        certificado_cliente,
        certificado_ca_clientes
    )

    if not certificado_valido:
        return None, None, buffer, "Certificado do cliente não foi assinado por uma CA confiável."

    # O CN é obtido apenas para log/apresentação.
    # A autenticação real não depende apenas do CN.
    cn_cliente = obter_common_name_certificado(certificado_cliente)

    # Calcula o fingerprint SHA-256 do certificado apresentado pelo cliente.
    fingerprint_cliente = obter_fingerprint_sha256(certificado_cliente)

    # Carrega a lista de clientes autorizados.
    clientes_autorizados = carregar_clientes_autorizados()

    # Verifica se o nome do cliente está no arquivo de autorizados.
    if id_cliente not in clientes_autorizados:
        return None, None, buffer, f"Cliente '{id_cliente}' não está autorizado."

    # Pega o fingerprint esperado para esse cliente.
    fingerprint_esperado = clientes_autorizados[id_cliente]

    # Compara o fingerprint do certificado recebido com o fingerprint autorizado.
    if normalizar_fingerprint(fingerprint_cliente) != normalizar_fingerprint(fingerprint_esperado):
        return None, None, buffer, "Fingerprint do certificado não corresponde ao cliente autorizado."

    # Pega a chave pública do cliente a partir do certificado dele.
    chave_publica_cliente = certificado_cliente.public_key()

    # Monta exatamente os dados que o cliente deveria ter assinado.
    # Isso liga o cliente, o desafio e a chave de sessão criptografada.
    dados_assinados = (
        f"{id_cliente}|{desafio_broker_b64}|{chave_sessao_criptografada_b64}"
    ).encode("utf-8")

    # Converte a assinatura de Base64 para bytes.
    assinatura = b64_decode(assinatura_b64)

    # Verifica se a assinatura foi feita com a chave privada do cliente.
    assinatura_valida = verificar_assinatura_dados(
        chave_publica_cliente,
        assinatura,
        dados_assinados
    )

    if not assinatura_valida:
        return None, None, buffer, "Assinatura do cliente inválida."

    # Converte a chave de sessão criptografada de Base64 para bytes.
    chave_sessao_criptografada = b64_decode(chave_sessao_criptografada_b64)

    # Descriptografa a chave de sessão AES usando a chave privada do broker.
    chave_sessao = descriptografar_com_chave_privada(
        chave_privada_broker,
        chave_sessao_criptografada
    )

    print(f"[✓] Cliente autenticado: {id_cliente}")
    print(f"    CN do certificado: {cn_cliente}")
    print(f"    Fingerprint: {fingerprint_cliente}")

    # A partir daqui, a conexão já usa a chave de sessão AES.
    enviar_criptografado(conn, chave_sessao, {
        "tipo": "resposta",
        "mensagem": f"Cliente {id_cliente} autenticado e conectado com sucesso."
    })

    return id_cliente, chave_sessao, buffer, None


# ============================================================
# Bufferização de mensagens
# ============================================================

def entregar_pendentes(id_cliente, conn, chave_sessao):
    """
    Entrega mensagens que ficaram pendentes enquanto o cliente estava offline.
    """

    # Descobre quais tópicos possuem esse cliente inscrito.
    with lock:
        topicos_cliente = [
            topico for topico, inscritos in subscricoes.items()
            if id_cliente in inscritos
        ]

    # Percorre os tópicos nos quais o cliente está inscrito.
    for topico in topicos_cliente:
        with lock:
            entradas = list(mensagens_topico.get(topico, []))

        # Percorre as mensagens guardadas no buffer do tópico.
        for entrada in entradas:
            with lock:
                pendente = id_cliente in entrada["pendentes"]

            # Se a mensagem ainda está pendente para esse cliente, entrega.
            if pendente:
                try:
                    enviar_criptografado(
                        conn,
                        chave_sessao,
                        entrada["pacote"]
                    )

                    # Depois de entregar, remove o cliente da lista de pendentes.
                    with lock:
                        entrada["pendentes"].discard(id_cliente)

                    print(
                        f"[↓] Mensagem pendente entregue a "
                        f"{id_cliente} no tópico {topico}"
                    )

                except Exception as e:
                    print(f"[!] Falha ao entregar pendente para {id_cliente}: {e}")
                    break


def limpar_mensagens_entregues(topico):
    """
    Remove do buffer as mensagens que já foram entregues
    para todos os destinatários.
    """
    with lock:
        if topico in mensagens_topico:
            mensagens_topico[topico] = [
                entrada for entrada in mensagens_topico[topico]
                if len(entrada["pendentes"]) > 0
            ]


# ============================================================
# Tratamento do cliente
# ============================================================

def tratar_cliente(conn, addr):
    """
    Trata um cliente conectado ao broker.

    Cada cliente roda em uma thread separada, permitindo múltiplos clientes
    conectados ao mesmo tempo.
    """
    id_cliente = None
    chave_sessao = None

    try:
        print(f"[+] Nova conexão TCP: {addr}")

        # Antes de aceitar comandos, executa o handshake próprio.
        id_cliente, chave_sessao, buffer, erro = realizar_handshake(conn)

        if erro:
            enviar_json(conn, {
                "tipo": "erro",
                "mensagem": erro
            })
            print(f"[!] Falha no handshake com {addr}: {erro}")
            return

        # Salva o cliente como conectado.
        with lock:
            clientes_conectados[id_cliente] = {
                "conn": conn,
                "chave_sessao": chave_sessao
            }

        # Depois do handshake, todos os pacotes recebidos são criptografados.
        while True:
            pacote, buffer = receber_criptografado(
                conn,
                chave_sessao,
                buffer
            )

            if pacote is None:
                break

            tipo = pacote.get("tipo")

            # ── SOLICITAR PENDENTES ─────────────────────────────────────
            if tipo == "solicitar_pendentes":
                print(f"[↓] {id_cliente} solicitou mensagens pendentes.")

                entregar_pendentes(id_cliente, conn, chave_sessao)

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "resposta",
                    "mensagem": "Mensagens pendentes entregues."
                })

                # Após entregar pendentes, remove do buffer mensagens já finalizadas.
                with lock:
                    topicos_lista = list(topicos)

                for topico in topicos_lista:
                    limpar_mensagens_entregues(topico)

            # ── CRIAR TÓPICO ────────────────────────────────────────────
            elif tipo == "criar_topico":
                topico = pacote.get("topico")

                if not topico:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": "Nome do tópico não informado."
                    })
                    continue

                # Cria o tópico e inscreve automaticamente o criador nele.
                with lock:
                    topicos.add(topico)
                    subscricoes.setdefault(topico, set())
                    mensagens_topico.setdefault(topico, [])
                    subscricoes[topico].add(id_cliente)

                print(f"[+] Tópico criado: {topico}")
                print(f"[+] {id_cliente} inscrito automaticamente em {topico}")

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "resposta",
                    "mensagem": (
                        f"Tópico '{topico}' criado com sucesso. "
                        f"Você foi inscrito automaticamente nele."
                    )
                })

            # ── INSCREVER ───────────────────────────────────────────────
            elif tipo == "inscrever":
                topico = pacote.get("topico")

                if not topico:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": "Nome do tópico não informado."
                    })
                    continue

                # Se o tópico não existir, cria.
                # Depois adiciona o cliente na lista de inscritos.
                with lock:
                    if topico not in topicos:
                        topicos.add(topico)
                        subscricoes.setdefault(topico, set())
                        mensagens_topico.setdefault(topico, [])

                    subscricoes[topico].add(id_cliente)

                print(f"[+] {id_cliente} se inscreveu em {topico}")

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "resposta",
                    "mensagem": f"Você se inscreveu no tópico '{topico}'."
                })

            # ── DESINSCREVER ────────────────────────────────────────────
            elif tipo == "desinscrever":
                topico = pacote.get("topico")

                if not topico:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": "Nome do tópico não informado."
                    })
                    continue

                with lock:
                    if topico not in subscricoes:
                        enviar_criptografado(conn, chave_sessao, {
                            "tipo": "erro",
                            "mensagem": f"O tópico '{topico}' não existe."
                        })
                        continue

                    inscritos = subscricoes.get(topico, set())

                    if id_cliente not in inscritos:
                        enviar_criptografado(conn, chave_sessao, {
                            "tipo": "erro",
                            "mensagem": f"Você não está inscrito no tópico '{topico}'."
                        })
                        continue

                    # Regra do projeto: não permite que o último inscrito saia.
                    if len(inscritos) == 1:
                        enviar_criptografado(conn, chave_sessao, {
                            "tipo": "erro",
                            "mensagem": (
                                f"Não é possível sair do tópico '{topico}', "
                                f"pois você é o último inscrito nele."
                            )
                        })
                        print(
                            f"[!] {id_cliente} tentou sair de {topico}, "
                            f"mas é o último inscrito"
                        )
                        continue

                    # Remove o cliente do tópico.
                    subscricoes[topico].remove(id_cliente)

                    # Remove mensagens pendentes para esse cliente nesse tópico.
                    for entrada in mensagens_topico.get(topico, []):
                        entrada["pendentes"].discard(id_cliente)

                limpar_mensagens_entregues(topico)

                print(f"[-] {id_cliente} saiu do tópico {topico}")

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "desinscrito",
                    "topico": topico,
                    "mensagem": f"Você saiu do tópico '{topico}'."
                })

            # ── PUBLICAR ────────────────────────────────────────────────
            elif tipo == "publicar":
                topico = pacote.get("topico")

                # O payload já chega criptografado pelo cliente.
                # O broker não possui a chave E2E do tópico.
                payload_criptografado = pacote.get("payload_criptografado")

                if not topico:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": "Nome do tópico não informado."
                    })
                    continue

                # O broker não aceita mensagem em texto puro.
                if not payload_criptografado:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": (
                            "Payload criptografado não informado. "
                            "O broker não deve receber mensagem em texto puro."
                        )
                    })
                    continue

                with lock:
                    if topico not in topicos:
                        enviar_criptografado(conn, chave_sessao, {
                            "tipo": "erro",
                            "mensagem": (
                                f"Não é possível enviar mensagem. "
                                f"O tópico '{topico}' não existe."
                            )
                        })
                        print(
                            f"[!] {id_cliente} tentou publicar "
                            f"em tópico inexistente: {topico}"
                        )
                        continue

                    inscritos = subscricoes.get(topico, set()).copy()

                # O cliente só pode publicar se estiver inscrito no tópico.
                if id_cliente not in inscritos:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": (
                            f"Não é possível enviar mensagem em '{topico}', "
                            f"pois você não está inscrito nesse tópico."
                        )
                    })
                    print(
                        f"[!] {id_cliente} tentou publicar em {topico} "
                        f"sem estar inscrito"
                    )
                    continue

                print(
                    f"[{topico}] {id_cliente} publicou uma mensagem "
                    f"com payload criptografado."
                )

                # Monta o pacote que será encaminhado aos outros inscritos.
                # O broker encaminha o payload criptografado, sem descriptografar.
                pacote_mensagem = {
                    "tipo": "mensagem",
                    "topico": topico,
                    "remetente": id_cliente,
                    "payload_criptografado": payload_criptografado
                }

                # Destinatários são todos os inscritos, exceto quem enviou.
                destinatarios = inscritos - {id_cliente}

                # Cria entrada no buffer.
                # Quem estiver offline permanece em "pendentes".
                entrada = {
                    "pacote": pacote_mensagem,
                    "pendentes": set(destinatarios)
                }

                with lock:
                    mensagens_topico.setdefault(topico, []).append(entrada)

                # Tenta entregar a mensagem imediatamente para os clientes online.
                for destinatario in destinatarios:
                    with lock:
                        info_destino = clientes_conectados.get(destinatario)

                    if info_destino:
                        try:
                            enviar_criptografado(
                                info_destino["conn"],
                                info_destino["chave_sessao"],
                                pacote_mensagem
                            )

                            # Se entregou, remove da lista de pendentes.
                            with lock:
                                entrada["pendentes"].discard(destinatario)

                            print(f"[{topico}] {id_cliente} → {destinatario}")

                        except (
                            ConnectionResetError,
                            ConnectionAbortedError,
                            OSError
                        ):
                            # Se falhar, considera o cliente desconectado
                            # e mantém a mensagem pendente.
                            with lock:
                                clientes_conectados.pop(destinatario, None)

                            print(
                                f"[!] {destinatario} estava desconectado. "
                                f"Mensagem guardada no buffer."
                            )
                    else:
                        print(
                            f"[+] {destinatario} está offline. "
                            f"Mensagem guardada no buffer."
                        )

                # Remove do buffer mensagens que já foram entregues a todos.
                limpar_mensagens_entregues(topico)

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "resposta",
                    "mensagem": f"Mensagem publicada no tópico '{topico}'."
                })

            # ── LISTAR TÓPICOS ──────────────────────────────────────────
            elif tipo == "listar_topicos":
                with lock:
                    lista = list(topicos)

                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "topicos",
                    "topicos": lista
                })

            # Caso o comando recebido não exista.
            else:
                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "erro",
                    "mensagem": "Comando desconhecido."
                })

    # Erros comuns quando o cliente fecha a conexão.
    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass

    # Outros erros inesperados.
    except Exception as e:
        nome = id_cliente if id_cliente else addr
        print(f"[!] Erro com cliente {nome}: {e}")

    finally:
        # Remove o cliente da lista de conectados ao encerrar.
        if id_cliente:
            with lock:
                clientes_conectados.pop(id_cliente, None)

            print(f"[-] Cliente {id_cliente} encerrou conexão")

        else:
            print(f"[-] Cliente {addr} encerrou conexão")

        try:
            conn.close()
        except Exception:
            pass


# ============================================================
# Inicialização do broker TCP
# ============================================================

def iniciar_broker():
    """
    Inicializa o broker TCP.

    Antes de abrir a porta, verifica se todos os arquivos necessários existem.
    """
    if not os.path.exists(CERT_SERVIDOR):
        print(f"[!] Certificado do servidor não encontrado: {CERT_SERVIDOR}")
        return

    if not os.path.exists(CHAVE_SERVIDOR):
        print(f"[!] Chave privada do servidor não encontrada: {CHAVE_SERVIDOR}")
        return

    if not os.path.exists(CA_CLIENTES):
        print(f"[!] CA dos clientes não encontrada: {CA_CLIENTES}")
        print("[!] Esse arquivo deve ser a CA que assinou os certificados dos clientes.")
        return

    if not os.path.exists(ARQUIVO_CLIENTES_AUTORIZADOS):
        print(
            f"[!] Arquivo de clientes autorizados não encontrado: "
            f"{ARQUIVO_CLIENTES_AUTORIZADOS}"
        )
        print("[!] Crie esse arquivo antes de iniciar o broker.")
        return

    # Cria o socket TCP.
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Permite reutilizar a porta rapidamente caso o broker seja reiniciado.
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Associa o socket ao endereço e porta configurados.
    servidor.bind((BROKER_HOST, BROKER_PORT))

    # Coloca o broker em modo de escuta.
    servidor.listen(5)

    print(f"[*] Broker TCP ouvindo em {BROKER_HOST}:{BROKER_PORT}")
    print("[*] TLS/SSL não está sendo usado.")
    print("[*] Envelopamento digital próprio ativo.")
    print("[*] Autenticação de clientes por certificado e assinatura ativa.")
    print("[*] Payload ponta a ponta: broker não decodifica mensagens.")

    # Loop principal: aceita conexões de clientes.
    while True:
        conn, addr = servidor.accept()

        # Cada cliente é tratado em uma thread separada.
        thread = threading.Thread(
            target=tratar_cliente,
            args=(conn, addr)
        )
        thread.daemon = True
        thread.start()


# Só inicia o broker se este arquivo for executado diretamente.
if __name__ == "__main__":
    iniciar_broker()