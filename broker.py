import socket
import threading
import json

BROKER_HOST = "0.0.0.0"
BROKER_PORT = 1883

clientes_conectados = {}  # id_cliente: conexão socket
topicos = set()           # conjunto de tópicos criados
subscricoes = {}          # topico: conjunto de clientes inscritos
mensagens_pendentes = {}  # guarda mensagens para clientes que estão offline

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

                # Cliente informa seu nome
                if tipo == "conectar":
                    id_cliente = pacote.get("id")

                    with lock:
                        clientes_conectados[id_cliente] = conn

                        #Pega as mensagens pendentes para esse cliente, se houver
                        pendentes = mensagens_pendentes.pop(id_cliente, [])


                    print(f"[✓] Cliente conectado: {id_cliente}")

                    enviar(conn, {
                        "tipo": "resposta",
                        "mensagem": f"Cliente {id_cliente} conectado com sucesso."
                    })

                     # Envia as mensagens que chegaram enquanto o cliente estava offline
                    if pendentes:
                        print(f"[+] Enviando {len(pendentes)} mensagem(ns) pendente(s) para {id_cliente}")

                        for mensagem_pendente in pendentes:
                            enviar(conn, mensagem_pendente)

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
                        # Verifica se o tópico existe
                        if topico not in topicos:
                            enviar(conn, {
                                "tipo": "erro",
                                "mensagem": f"Não é possível enviar mensagem. O tópico '{topico}' não existe."
                            })

                            print(f"[!] {id_cliente} tentou publicar em tópico inexistente: {topico}")
                            continue

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

    except (ConnectionResetError, ConnectionAbortedError, OSError):
        pass

    except Exception as e:
        nome = id_cliente if id_cliente else addr
        print(f"[!] Erro com cliente {nome}: {e}")

    finally:
        if id_cliente:
            with lock:
                clientes_conectados.pop(id_cliente, None)

                for topico in subscricoes:
                    subscricoes[topico].discard(id_cliente)

            print(f"[-] Cliente {id_cliente} encerrou conexão")

        else:
            print(f"[-] Cliente {addr} encerrou conexão")

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