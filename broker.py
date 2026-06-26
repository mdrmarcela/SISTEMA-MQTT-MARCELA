import socket
import threading
import json
import ssl
import os
import hashlib

BROKER_HOST = "0.0.0.0"
BROKER_PORT = 1883

CERT_SERVIDOR = os.path.join("certs", "servidor", "servidor.crt")
CHAVE_SERVIDOR = os.path.join("certs", "servidor", "servidor.key")

# CA usada para validar os certificados dos clientes.
# Se os certificados dos clientes foram assinados pelo professor, use:
# CA_CLIENTES = os.path.join("certs", "ca_professor.crt")
#
# Se os certificados dos clientes foram assinados pela sua CA antiga,
# salve essa CA como certs/ca_clientes.crt
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


def enviar(conn, pacote):
    """
    Envia um pacote JSON para o cliente.
    O \n serve para separar uma mensagem da outra.
    """
    mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
    conn.sendall(mensagem.encode("utf-8"))


def obter_common_name(conn):
    """
    Pega o CN do certificado apenas para registro/log.
    A autenticação real NÃO depende apenas do CN.
    """
    certificado = conn.getpeercert()

    if not certificado:
        return None

    for grupo in certificado.get("subject", []):
        for chave, valor in grupo:
            if chave == "commonName":
                return valor

    return None


def normalizar_fingerprint(fingerprint):
    """
    Remove ':' e deixa tudo minúsculo para comparar fingerprints.
    """
    if not fingerprint:
        return ""

    return fingerprint.replace(":", "").strip().lower()


def obter_fingerprint_certificado(conn):
    """
    Calcula o fingerprint SHA-256 do certificado apresentado pelo cliente.
    """
    certificado_binario = conn.getpeercert(binary_form=True)

    if not certificado_binario:
        return None

    return hashlib.sha256(certificado_binario).hexdigest()


def carregar_clientes_autorizados():
    """
    Carrega o JSON com os clientes autorizados e seus fingerprints.
    Formato:
    {
        "cliente1": "fingerprint_sha256",
        "cliente2": "fingerprint_sha256"
    }
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


def autenticar_cliente(conn, nome_informado):
    """
    Autentica o cliente usando:
    1. validação SSL/mTLS feita pelo contexto SSL;
    2. fingerprint SHA-256 do certificado;
    3. lista local de clientes autorizados.

    O CN é usado apenas para log, não como única validação.
    """
    cn_certificado = obter_common_name(conn)
    fingerprint_cliente = obter_fingerprint_certificado(conn)
    clientes_autorizados = carregar_clientes_autorizados()

    if not nome_informado:
        return False, "Autenticação falhou. Nome do cliente não informado."

    if not fingerprint_cliente:
        return False, "Autenticação falhou. Certificado do cliente não encontrado."

    if nome_informado not in clientes_autorizados:
        return False, f"Autenticação falhou. Cliente '{nome_informado}' não está autorizado."

    fingerprint_esperado = clientes_autorizados[nome_informado]

    if normalizar_fingerprint(fingerprint_cliente) != normalizar_fingerprint(fingerprint_esperado):
        return False, "Autenticação falhou. Certificado não corresponde ao cliente informado."

    print(f"[✓] Cliente autenticado: {nome_informado}")
    print(f"    CN do certificado: {cn_certificado}")
    print(f"    Fingerprint: {fingerprint_cliente}")

    return True, "Cliente autenticado com sucesso."


def entregar_pendentes(id_cliente, conn):
    """
    Entrega mensagens pendentes dos tópicos em que o cliente está inscrito.
    """
    with lock:
        topicos_cliente = [
            t for t, inscritos in subscricoes.items()
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
                    enviar(conn, entrada["pacote"])

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
    Remove do buffer mensagens já entregues a todos os inscritos.
    """
    with lock:
        if topico in mensagens_topico:
            mensagens_topico[topico] = [
                entrada for entrada in mensagens_topico[topico]
                if len(entrada["pendentes"]) > 0
            ]


def tratar_cliente(conn, addr):
    id_cliente = None
    buffer = ""

    try:
        print(f"[+] Nova conexão SSL: {addr}")

        enviar(conn, {
            "tipo": "info",
            "mensagem": "Conectado ao broker."
        })

        while True:
            dados = conn.recv(4096)

            if not dados:
                break

            buffer += dados.decode("utf-8")

            while "\n" in buffer:
                linha, buffer = buffer.split("\n", 1)

                if not linha.strip():
                    continue

                pacote = json.loads(linha)
                tipo = pacote.get("tipo")

                # ── CONECTAR ────────────────────────────────────────────────
                if tipo == "conectar":
                    nome_informado = pacote.get("id")

                    sucesso, mensagem = autenticar_cliente(
                        conn,
                        nome_informado
                    )

                    if not sucesso:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": mensagem
                        })
                        print(f"[!] {mensagem}")
                        return

                    id_cliente = nome_informado

                    with lock:
                        clientes_conectados[id_cliente] = conn

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": (
                            f"Cliente {id_cliente} autenticado "
                            f"e conectado com sucesso."
                        )
                    })

                elif not id_cliente:
                    enviar(conn, {
                        "tipo": "erro",
                        "mensagem": "Cliente ainda não autenticado."
                    })

                # ── SOLICITAR PENDENTES ─────────────────────────────────────
                elif tipo == "solicitar_pendentes":
                    print(f"[↓] {id_cliente} solicitou mensagens pendentes.")

                    entregar_pendentes(id_cliente, conn)

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": "Mensagens pendentes entregues."
                    })

                    with lock:
                        topicos_lista = list(topicos)

                    for t in topicos_lista:
                        limpar_mensagens_entregues(t)

                # ── CRIAR TÓPICO ────────────────────────────────────────────
                elif tipo == "criar_topico":
                    topico = pacote.get("topico")

                    if not topico:
                        enviar(conn, {
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

                    enviar(conn, {
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
                        enviar(conn, {
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

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Você se inscreveu no tópico '{topico}'."
                    })

                # ── DESINSCREVER ────────────────────────────────────────────
                elif tipo == "desinscrever":
                    topico = pacote.get("topico")

                    if not topico:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Nome do tópico não informado."
                        })
                        continue

                    with lock:
                        if topico not in subscricoes:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"O tópico '{topico}' não existe."
                            })
                            continue

                        inscritos = subscricoes.get(topico, set())

                        if id_cliente not in inscritos:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": (
                                    f"Você não está inscrito no tópico '{topico}'."
                                )
                            })
                            continue

                        if len(inscritos) == 1:
                            enviar(conn, {
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

                    enviar(conn, {
                        "tipo": "desinscrito",
                        "topico": topico,
                        "mensagem": f"Você saiu do tópico '{topico}'."
                    })

                # ── PUBLICAR ────────────────────────────────────────────────
                elif tipo == "publicar":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")

                    if not topico:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Nome do tópico não informado."
                        })
                        continue

                    if not mensagem:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Mensagem não informada."
                        })
                        continue

                    with lock:
                        if topico not in topicos:
                            enviar(conn, {
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
                        print(
                            f"[!] {id_cliente} tentou publicar em {topico} "
                            f"sem estar inscrito"
                        )
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": (
                                f"Não é possível enviar mensagem em '{topico}', "
                                f"pois você não está inscrito nesse tópico."
                            )
                        })
                        continue

                    print(f"[{topico}] {id_cliente}: {mensagem}")

                    pacote_mensagem = {
                        "tipo": "mensagem",
                        "topico": topico,
                        "remetente": id_cliente,
                        "mensagem": mensagem
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
                            conn_destino = clientes_conectados.get(destinatario)

                        if conn_destino:
                            try:
                                enviar(conn_destino, pacote_mensagem)

                                with lock:
                                    entrada["pendentes"].discard(destinatario)

                                print(
                                    f"[{topico}] {id_cliente} → {destinatario}"
                                )

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

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Mensagem publicada no tópico '{topico}'."
                    })

                # ── LISTAR TÓPICOS ──────────────────────────────────────────
                elif tipo == "listar_topicos":
                    with lock:
                        lista = list(topicos)

                    enviar(conn, {
                        "tipo": "topicos",
                        "topicos": lista
                    })

                else:
                    enviar(conn, {
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


def iniciar_broker():
    if not os.path.exists(CERT_SERVIDOR):
        print(f"[!] Certificado do servidor não encontrado: {CERT_SERVIDOR}")
        return

    if not os.path.exists(CHAVE_SERVIDOR):
        print(f"[!] Chave privada do servidor não encontrada: {CHAVE_SERVIDOR}")
        return

    if not os.path.exists(CA_CLIENTES):
        print(f"[!] CA dos clientes não encontrada: {CA_CLIENTES}")
        print("[!] Coloque nesse arquivo a CA que assinou os certificados dos clientes.")
        return

    if not os.path.exists(ARQUIVO_CLIENTES_AUTORIZADOS):
        print(f"[!] Arquivo de clientes autorizados não encontrado: {ARQUIVO_CLIENTES_AUTORIZADOS}")
        print("[!] Crie o arquivo antes de iniciar o broker.")
        return

    contexto_ssl = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    contexto_ssl.load_cert_chain(
        certfile=CERT_SERVIDOR,
        keyfile=CHAVE_SERVIDOR
    )

    contexto_ssl.load_verify_locations(
        cafile=CA_CLIENTES
    )

    contexto_ssl.verify_mode = ssl.CERT_REQUIRED

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    servidor.bind((BROKER_HOST, BROKER_PORT))
    servidor.listen(5)

    print(f"[*] Broker com autenticação ouvindo em {BROKER_HOST}:{BROKER_PORT}")
    print("[*] Validação TLS/mTLS ativa.")
    print("[*] Validação adicional por fingerprint ativa.")

    while True:
        conn_original, addr = servidor.accept()

        try:
            conn_segura = contexto_ssl.wrap_socket(
                conn_original,
                server_side=True
            )

            print(f"[✓] Conexão SSL aceita de {addr}")

        except ssl.SSLError as e:
            print(f"[!] Falha na autenticação SSL de {addr}: {e}")
            conn_original.close()
            continue

        thread = threading.Thread(
            target=tratar_cliente,
            args=(conn_segura, addr)
        )
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    iniciar_broker()