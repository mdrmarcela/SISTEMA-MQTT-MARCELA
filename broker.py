import socket
import threading
import json

BROKER_HOST = "0.0.0.0"
BROKER_PORT = 1883

clientes_conectados = {}  # id_cliente -> conexão socket
topicos = set()           # conjunto de tópicos criados
subscricoes = {}          # topico -> conjunto de clientes inscritos

lock = threading.Lock()


def enviar(conn, pacote):
    """
    Envia um pacote JSON para o cliente.
    O \n serve para separar uma mensagem da outra.
    """
    mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
    conn.sendall(mensagem.encode("utf-8"))


def tratar_cliente(conn, addr):
    id_cliente = None
    buffer = ""

    try:
        print(f"[+] Nova conexão: {addr}")

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

                # Cliente informa seu nome/id
                if tipo == "conectar":
                    id_cliente = pacote.get("id")

                    with lock:
                        clientes_conectados[id_cliente] = conn

                    print(f"[✓] Cliente conectado: {id_cliente}")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Cliente {id_cliente} conectado com sucesso."
                    })

                # Criar tópico
                elif tipo == "criar_topico":
                    topico = pacote.get("topico")

                    with lock:
                        topicos.add(topico)
                        subscricoes.setdefault(topico, set())

                        # Quem cria o tópico já fica inscrito automaticamente
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
                        inscrito = (
                            topico in subscricoes
                            and id_cliente in subscricoes[topico]
                        )

                        if inscrito:
                            subscricoes[topico].remove(id_cliente)

                    if inscrito:
                        print(f"[-] {id_cliente} saiu do tópico {topico}")

                        enviar(conn, {
                            "tipo": "resposta",
                            "mensagem": f"Você saiu do tópico '{topico}'."
                        })
                    else:
                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": f"Você não está inscrito no tópico '{topico}'."
                        })

                # Publicar mensagem
                elif tipo == "publicar":
                    topico = pacote.get("topico")
                    mensagem = pacote.get("mensagem")

                    with lock:
                        inscritos = subscricoes.get(topico, set()).copy()

                    # Bloqueia envio se o cliente não estiver inscrito no tópico
                    if id_cliente not in inscritos:
                        print(f"[!] {id_cliente} tentou publicar em {topico} sem estar inscrito")

                        enviar(conn, {
                            "tipo": "erro",
                            "mensagem": f"Não é possível enviar mensagem em '{topico}', pois você não está inscrito nesse tópico."
                        })

                        continue

                    print(f"[{topico}] {id_cliente}: {mensagem}")

                    # Envia a mensagem para todos os inscritos, menos para quem publicou
                    for destinatario in inscritos:
                        if destinatario == id_cliente:
                            continue

                        conn_destino = clientes_conectados.get(destinatario)

                        if conn_destino:
                            enviar(conn_destino, {
                                "tipo": "mensagem",
                                "topico": topico,
                                "remetente": id_cliente,
                                "mensagem": mensagem
                            })

                            print(f"[{topico}] {id_cliente} → {destinatario}")

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

    except Exception as e:
        print(f"[!] Erro com cliente {addr}: {e}")

    finally:
        if id_cliente:
            with lock:
                clientes_conectados.pop(id_cliente, None)

                for topico in subscricoes:
                    subscricoes[topico].discard(id_cliente)

            print(f"[-] Cliente desconectado: {id_cliente}")

        conn.close()


def iniciar_broker():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    servidor.bind((BROKER_HOST, BROKER_PORT))
    servidor.listen(5)

    print(f"[*] Broker ouvindo em {BROKER_HOST}:{BROKER_PORT}")

    while True:
        conn, addr = servidor.accept()
        thread = threading.Thread(target=tratar_cliente, args=(conn, addr))
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    iniciar_broker()