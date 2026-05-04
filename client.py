import socket
import threading
import json
from datetime import datetime

BROKER_HOST = "localhost"
BROKER_PORT = 1883


class ClienteWeb:
    def __init__(self):
        self.socket = None
        self.nome_cliente = ""
        self.conectado = False
        self.mensagens = []
        self.topicos = []
        self.buffer = ""

    def enviar(self, pacote):
        """
        Envia um pacote JSON para o broker.
        O \n serve para separar uma mensagem da outra.
        """
        mensagem = json.dumps(pacote, ensure_ascii=False) + "\n"
        self.socket.sendall(mensagem.encode("utf-8"))

    def conectar(self, nome_cliente):
        try:
            self.nome_cliente = nome_cliente

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((BROKER_HOST, BROKER_PORT))

            self.conectado = True

            self.enviar({
                "tipo": "conectar",
                "id": self.nome_cliente
            })

            thread = threading.Thread(target=self.receber_mensagens)
            thread.daemon = True
            thread.start()

            return True, f"Cliente {self.nome_cliente} conectado com sucesso."

        except Exception as e:
            self.conectado = False
            return False, f"Erro ao conectar: {e}"

    def receber_mensagens(self):
        while self.conectado:
            try:
                dados = self.socket.recv(4096)

                if not dados:
                    break

                self.buffer += dados.decode("utf-8")

                while "\n" in self.buffer:
                    linha, self.buffer = self.buffer.split("\n", 1)

                    if not linha.strip():
                        continue

                    pacote = json.loads(linha)
                    tipo = pacote.get("tipo")

                    if tipo == "mensagem":
                        topico = pacote.get("topico")
                        remetente = pacote.get("remetente")
                        mensagem = pacote.get("mensagem")
                        hora = datetime.now().strftime("%H:%M")

                        texto = f"[{topico}] {remetente}: {mensagem} [{hora}]"
                        self.mensagens.append(texto)

                    elif tipo == "resposta":
                        mensagem = pacote.get("mensagem")
                        hora = datetime.now().strftime("%H:%M")

                        texto = f"Sistema: {mensagem} [{hora}]"
                        self.mensagens.append(texto)

                    elif tipo == "topicos":
                        self.topicos = pacote.get("topicos", [])

                    elif tipo == "erro":
                        mensagem = pacote.get("mensagem")
                        self.mensagens.append(f"Erro: {mensagem}")

            except Exception as e:
                self.mensagens.append(f"Erro ao receber mensagem: {e}")
                break

        self.conectado = False

    def criar_topico(self, topico):
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "criar_topico",
            "id": self.nome_cliente,
            "topico": topico
        })

        return True, f"Solicitação para criar o tópico '{topico}' enviada."

    def inscrever(self, topico):
        if not self.conectado:
            return False, "Cliente não está conectado."

        self.enviar({
            "tipo": "inscrever",
            "id": self.nome_cliente,
            "topico": topico
        })

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

        self.enviar({
            "tipo": "publicar",
            "id": self.nome_cliente,
            "topico": topico,
            "mensagem": mensagem
        })

        return True, f"Mensagem enviada para o tópico '{topico}'."

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

        if self.socket:
            self.socket.close()