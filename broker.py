import socket
import threading
import json
import os
import secrets

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


BROKER_HOST = "0.0.0.0"
BROKER_PORT = 1883

CERT_SERVIDOR = os.path.join("certs", "servidor", "servidor.crt")
CHAVE_SERVIDOR = os.path.join("certs", "servidor", "servidor.key")

# Certificado da autoridade que assinou os certificados dos clientes.
# Se o próprio broker assinou os clientes usando uma CA local,
# coloque esse certificado aqui.
CA_CLIENTES = os.path.join("certs", "ca_clientes.crt")

ARQUIVO_CLIENTES_AUTORIZADOS = os.path.join(
    "certs",
    "clientes_autorizados.json"
)

clientes_conectados = {}
topicos = set()
subscricoes = {}
mensagens_topico = {}

lock = threading.Lock()


# ============================================================
# Comunicação TCP com pacotes JSON separados por \n
# ============================================================

def enviar_json(conn, pacote):
    mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
    conn.sendall(mensagem.encode("utf-8"))


def receber_json(conn, buffer):
    while "\n" not in buffer:
        dados = conn.recv(4096)

        if not dados:
            return None, buffer

        buffer += dados.decode("utf-8")

    linha, buffer = buffer.split("\n", 1)

    if not linha.strip():
        return receber_json(conn, buffer)

    return json.loads(linha), buffer


def enviar_criptografado(conn, chave_sessao, pacote):
    envelope = criptografar_json(chave_sessao, pacote)
    envelope["tipo"] = "envelope"

    enviar_json(conn, envelope)


def receber_criptografado(conn, chave_sessao, buffer):
    envelope, buffer = receber_json(conn, buffer)

    if envelope is None:
        return None, buffer

    if envelope.get("tipo") != "envelope":
        raise ValueError("Pacote recebido não está envelopado/criptografado.")

    pacote = descriptografar_json(chave_sessao, envelope)

    return pacote, buffer


# ============================================================
# Clientes autorizados
# ============================================================

def normalizar_fingerprint(fingerprint):
    if not fingerprint:
        return ""

    return fingerprint.replace(":", "").strip().lower()


def carregar_clientes_autorizados():
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
    Faz o handshake próprio, sem TLS.

    Fluxo:
    1. Broker envia certificado e desafio.
    2. Cliente valida certificado do broker.
    3. Cliente gera chave de sessão AES.
    4. Cliente criptografa a chave de sessão com a chave pública do broker.
    5. Cliente envia certificado, chave de sessão criptografada e assinatura.
    6. Broker valida certificado do cliente, assinatura e fingerprint.
    """

    buffer = ""

    certificado_broker_pem = certificado_para_pem(CERT_SERVIDOR)
    chave_privada_broker = carregar_chave_privada(CHAVE_SERVIDOR)
    certificado_ca_clientes = carregar_certificado(CA_CLIENTES)

    desafio_broker = secrets.token_bytes(32)
    desafio_broker_b64 = b64_encode(desafio_broker)

    enviar_json(conn, {
        "tipo": "handshake_broker",
        "certificado_broker": certificado_broker_pem,
        "desafio": desafio_broker_b64
    })

    pacote_cliente, buffer = receber_json(conn, buffer)

    if pacote_cliente is None:
        return None, None, buffer, "Cliente desconectou durante o handshake."

    if pacote_cliente.get("tipo") != "handshake_cliente":
        return None, None, buffer, "Handshake inválido. Pacote inicial do cliente incorreto."

    id_cliente = pacote_cliente.get("id")
    certificado_cliente_pem = pacote_cliente.get("certificado_cliente")
    chave_sessao_criptografada_b64 = pacote_cliente.get("chave_sessao")
    assinatura_b64 = pacote_cliente.get("assinatura")

    if not id_cliente:
        return None, None, buffer, "Cliente não informou identificação."

    if not certificado_cliente_pem:
        return None, None, buffer, "Cliente não enviou certificado."

    if not chave_sessao_criptografada_b64:
        return None, None, buffer, "Cliente não enviou chave de sessão criptografada."

    if not assinatura_b64:
        return None, None, buffer, "Cliente não enviou assinatura do desafio."

    certificado_cliente = carregar_certificado_pem_texto(certificado_cliente_pem)

    certificado_valido = verificar_assinatura_certificado(
        certificado_cliente,
        certificado_ca_clientes
    )

    if not certificado_valido:
        return None, None, buffer, "Certificado do cliente não foi assinado por uma CA confiável."

    cn_cliente = obter_common_name_certificado(certificado_cliente)
    fingerprint_cliente = obter_fingerprint_sha256(certificado_cliente)

    clientes_autorizados = carregar_clientes_autorizados()

    if id_cliente not in clientes_autorizados:
        return None, None, buffer, f"Cliente '{id_cliente}' não está autorizado."

    fingerprint_esperado = clientes_autorizados[id_cliente]

    if normalizar_fingerprint(fingerprint_cliente) != normalizar_fingerprint(fingerprint_esperado):
        return None, None, buffer, "Fingerprint do certificado não corresponde ao cliente autorizado."

    chave_publica_cliente = certificado_cliente.public_key()

    dados_assinados = (
        f"{id_cliente}|{desafio_broker_b64}|{chave_sessao_criptografada_b64}"
    ).encode("utf-8")

    assinatura = b64_decode(assinatura_b64)

    assinatura_valida = verificar_assinatura_dados(
        chave_publica_cliente,
        assinatura,
        dados_assinados
    )

    if not assinatura_valida:
        return None, None, buffer, "Assinatura do cliente inválida."

    chave_sessao_criptografada = b64_decode(chave_sessao_criptografada_b64)

    chave_sessao = descriptografar_com_chave_privada(
        chave_privada_broker,
        chave_sessao_criptografada
    )

    print(f"[✓] Cliente autenticado: {id_cliente}")
    print(f"    CN do certificado: {cn_cliente}")
    print(f"    Fingerprint: {fingerprint_cliente}")

    enviar_criptografado(conn, chave_sessao, {
        "tipo": "resposta",
        "mensagem": f"Cliente {id_cliente} autenticado e conectado com sucesso."
    })

    return id_cliente, chave_sessao, buffer, None


# ============================================================
# Bufferização de mensagens
# ============================================================

def entregar_pendentes(id_cliente, conn, chave_sessao):
    with lock:
        topicos_cliente = [
            topico for topico, inscritos in subscricoes.items()
            if id_cliente in inscritos
        ]

    for topico in topicos_cliente:
        with lock:
            entradas = list(mensagens_topico.get(topico, []))

        for entrada in entradas:
            with lock:
                pendente = id_cliente in entrada["pendentes"]

            if pendente:
                try:
                    enviar_criptografado(
                        conn,
                        chave_sessao,
                        entrada["pacote"]
                    )

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
    id_cliente = None
    chave_sessao = None

    try:
        print(f"[+] Nova conexão TCP: {addr}")

        id_cliente, chave_sessao, buffer, erro = realizar_handshake(conn)

        if erro:
            enviar_json(conn, {
                "tipo": "erro",
                "mensagem": erro
            })
            print(f"[!] Falha no handshake com {addr}: {erro}")
            return

        with lock:
            clientes_conectados[id_cliente] = {
                "conn": conn,
                "chave_sessao": chave_sessao
            }

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

                    subscricoes[topico].remove(id_cliente)

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
                payload_criptografado = pacote.get("payload_criptografado")

                if not topico:
                    enviar_criptografado(conn, chave_sessao, {
                        "tipo": "erro",
                        "mensagem": "Nome do tópico não informado."
                    })
                    continue

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

                pacote_mensagem = {
                    "tipo": "mensagem",
                    "topico": topico,
                    "remetente": id_cliente,
                    "payload_criptografado": payload_criptografado
                }

                destinatarios = inscritos - {id_cliente}

                entrada = {
                    "pacote": pacote_mensagem,
                    "pendentes": set(destinatarios)
                }

                with lock:
                    mensagens_topico.setdefault(topico, []).append(entrada)

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

                            with lock:
                                entrada["pendentes"].discard(destinatario)

                            print(f"[{topico}] {id_cliente} → {destinatario}")

                        except (
                            ConnectionResetError,
                            ConnectionAbortedError,
                            OSError
                        ):
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

            else:
                enviar_criptografado(conn, chave_sessao, {
                    "tipo": "erro",
                    "mensagem": "Comando desconhecido."
                })

    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass

    except Exception as e:
        nome = id_cliente if id_cliente else addr
        print(f"[!] Erro com cliente {nome}: {e}")

    finally:
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

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((BROKER_HOST, BROKER_PORT))
    servidor.listen(5)

    print(f"[*] Broker TCP ouvindo em {BROKER_HOST}:{BROKER_PORT}")
    print("[*] TLS/SSL não está sendo usado.")
    print("[*] Envelopamento digital próprio ativo.")
    print("[*] Autenticação de clientes por certificado e assinatura ativa.")
    print("[*] Payload ponta a ponta: broker não decodifica mensagens.")

    while True:
        conn, addr = servidor.accept()

        thread = threading.Thread(
            target=tratar_cliente,
            args=(conn, addr)
        )
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    iniciar_broker()