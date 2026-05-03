# SISTEMA PUBLISH/SUBSCRIBE

Este projeto consiste em uma infraestrutura de comunicação composta por um **broker** e um **cliente**, funcionando de forma semelhante ao protocolo **MQTT**, utilizando o modelo **publish/subscribe**.

## Parte 1

Nesta etapa inicial, o sistema deve permitir as seguintes funcionalidades:

* Criação de tópicos;
* Inscrição de clientes em tópicos;
* Publicação de mensagens;
* Recebimento de mensagens pelos clientes inscritos.

---

## Broker

O meu notebook será utilizado como **broker**.

Para iniciar o broker, execute o seguinte comando no terminal:

```bash
python broker.py
```

---

## Cliente 1 — Computador 1

No arquivo `cliente.py`, configure o IP do notebook que está rodando o broker:

```python
BROKER_HOST = "192.168.1.50"
BROKER_PORT = 1883
```

Depois, instale as dependências necessárias:

```bash
pip install streamlit
```

```bash
pip install streamlit-autorefresh
```

Em seguida, execute a interface do cliente com o comando:

```bash
streamlit run main.py
```

---

## Observação

O computador cliente precisa estar conectado à mesma rede que o notebook broker para conseguir se comunicar com ele.
