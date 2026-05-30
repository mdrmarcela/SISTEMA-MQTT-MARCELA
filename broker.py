import socket
import threading
import json
import ssl
import os

BROKER_HOST = "0.0.0.0"
BROKER_PORT = 1883

CERT_SERVIDOR = os.path.join("certs", "servidor", "servidor.crt")
CHAVE_SERVIDOR = os.path.join("certs", "servidor", "servidor.key")

clientes_conectados = {}   # id_cliente -> conexão socket
topicos = set()            # conjunto de tópicos criados
subscricoes = {}           # topico -> conjunto de clientes inscritos
mensagens_pendentes = {}   # id_cliente -> lista de mensagens pendentes

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
    Pega o Common Name do certificado do cliente.
    Exemplo: CN=cliente1
    """
    certificado = conn.getpeercert()

    if not certificado:
        return None

    for grupo in certificado.get("subject", []):
        for chave, valor in grupo:
            if chave == "commonName":
                return valor

    return None


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

                # Cliente informa seu nome
                if tipo == "conectar":
                    nome_informado = pacote.get("id")
                    cn_certificado = obter_common_name(conn)

                    if not nome_informado:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Autenticação falhou. Nome do cliente não informado."
                        })
                        print("[!] Cliente tentou conectar sem informar nome.")
                        return

                    if not cn_certificado:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Autenticação falhou. Certificado do cliente não encontrado."
                        })
                        print("[!] Cliente sem certificado.")
                        return

                    if nome_informado != cn_certificado:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": "Autenticação falhou. Nome do cliente não corresponde ao certificado."
                        })
                        print(
                            f"[!] Nome informado '{nome_informado}' diferente do certificado '{cn_certificado}'"
                        )
                        return

                    id_cliente = nome_informado

                    with lock:
                        clientes_conectados[id_cliente] = conn
                        pendentes = mensagens_pendentes.pop(id_cliente, [])

                    print(f"[✓] Cliente autenticado: {id_cliente}")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Cliente {id_cliente} autenticado e conectado com sucesso."
                    })

                    if pendentes:
                        print(f"[+] Enviando {len(pendentes)} mensagem(ns) pendente(s) para {id_cliente}")

                        for mensagem_pendente in pendentes:
                            enviar(conn, mensagem_pendente)

                elif not id_cliente:
                    enviar(conn, {
                        "tipo": "erro",
                        "mensagem": "Cliente ainda não autenticado."
                    })

                # Criar tópico
                elif tipo == "criar_topico":
                    topico = pacote.get("topico")

                    with lock:
                        topicos.add(topico)
                        subscricoes.setdefault(topico, set())

                        if id_cliente:
                            subscricoes[topico].add(id_cliente)

                    print(f"[+] Tópico criado: {topico}")
                    print(f"[+] {id_cliente} inscrito automaticamente em {topico}")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Tópico '{topico}' criado com sucesso. Você foi inscrito automaticamente nele."
                    })

                # Inscrever cliente em tópico
                elif tipo == "inscrever":
                    topico = pacote.get("topico")

                    with lock:
                        if topico not in topicos:
                            topicos.add(topico)
                            subscricoes.setdefault(topico, set())

                        subscricoes[topico].add(id_cliente)

                    print(f"[+] {id_cliente} se inscreveu em {topico}")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Você se inscreveu no tópico '{topico}'."
                    })

                # Desinscrever cliente de um tópico
                elif tipo == "desinscrever":
                    topico = pacote.get("topico")

                    with lock:
                        inscritos = subscricoes.get(topico, set())

                        if topico not in subscricoes:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"O tópico '{topico}' não existe."
                            })
                            continue

                        if id_cliente not in inscritos:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"Você não está inscrito no tópico '{topico}'."
                            })
                            continue

                        if len(inscritos) == 1:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"Não é possível sair do tópico '{topico}', pois você é o último inscrito nele."
                            })

                            print(f"[!] {id_cliente} tentou sair de {topico}, mas é o último inscrito")
                            continue

                        subscricoes[topico].remove(id_cliente)

                    print(f"[-] {id_cliente} saiu do tópico {topico}")

                    enviar(conn, {
                        "tipo": "desinscrito",
                        "topico": topico,
                        "mensagem": f"Você saiu do tópico '{topico}'."
                    })

                # Publicar mensagem
                elif tipo == "publicar":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")

                    with lock:
                        if topico not in topicos:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"Não é possível enviar mensagem. O tópico '{topico}' não existe."
                            })

                            print(f"[!] {id_cliente} tentou publicar em tópico inexistente: {topico}")
                            continue

                        inscritos = subscricoes.get(topico, set()).copy()

                    if id_cliente not in inscritos:
                        print(f"[!] {id_cliente} tentou publicar em {topico} sem estar inscrito")

                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": f"Não é possível enviar mensagem em '{topico}', pois você não está inscrito nesse tópico."
                        })

                        continue

                    print(f"[{topico}] {id_cliente}: {mensagem}")

                    pacote_mensagem = {
                        "tipo": "mensagem",
                        "topico": topico,
                        "remetente": id_cliente,
                        "mensagem": mensagem
                    }

                    for destinatario in inscritos:
                        if destinatario == id_cliente:
                            continue

                        with lock:
                            conn_destino = clientes_conectados.get(destinatario)

                        if conn_destino:
                            try:
                                enviar(conn_destino, pacote_mensagem)
                                print(f"[{topico}] {id_cliente} → {destinatario}")

                            except (ConnectionResetError, ConnectionAbortedError, OSError):
                                with lock:
                                    clientes_conectados.pop(destinatario, None)
                                    mensagens_pendentes.setdefault(destinatario, []).append(pacote_mensagem)

                                print(f"[!] {destinatario} estava desconectado. Mensagem guardada.")

                        else:
                            with lock:
                                mensagens_pendentes.setdefault(destinatario, []).append(pacote_mensagem)

                            print(f"[+] {destinatario} está offline. Mensagem guardada.")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Mensagem publicada no tópico '{topico}'."
                    })

                # Listar tópicos
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

        conn.close()


def iniciar_broker():
    if not os.path.exists(CERT_SERVIDOR):
        print(f"[!] Certificado do servidor não encontrado: {CERT_SERVIDOR}")
        return

    if not os.path.exists(CHAVE_SERVIDOR):
        print(f"[!] Chave privada do servidor não encontrada: {CHAVE_SERVIDOR}")
        return

    contexto_ssl = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    contexto_ssl.load_cert_chain(
        certfile=CERT_SERVIDOR,
        keyfile=CHAVE_SERVIDOR
    )

    contexto_ssl.load_verify_locations(
        cafile=CERT_SERVIDOR
    )

    contexto_ssl.verify_mode = ssl.CERT_REQUIRED

    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    servidor.bind((BROKER_HOST, BROKER_PORT))
    servidor.listen(5)

    print(f"[*] Broker com autenticação ouvindo em {BROKER_HOST}:{BROKER_PORT}")

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