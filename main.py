import streamlit as st
from datetime import datetime
from client import ClienteWeb
from utils.pubsub_utils import enviar_pub, enviar_sub
from streamlit_autorefresh import st_autorefresh
import json
import os

TOPICOS_PATH = "json/topicos.json"

def carregar_topicos():
    if os.path.exists(TOPICOS_PATH) and os.path.getsize(TOPICOS_PATH) > 0:
        with open(TOPICOS_PATH, "r") as f:
            return json.load(f)
    return []

def salvar_topicos(topicos):
    with open(TOPICOS_PATH, "w") as f:
        json.dump(topicos, f, indent=2)

# Estado
if 'cliente' not in st.session_state:
    st.session_state.cliente = ClienteWeb()
if 'topicos' not in st.session_state:
    st.session_state.topicos = carregar_topicos()
if 'mensagens_por_topico' not in st.session_state:
    st.session_state.mensagens_por_topico = {}

cliente = st.session_state.cliente

st.set_page_config(page_title="MQTT Chat Seguro", layout="wide")
st.title("🔐 Redes Chat")

# Autenticação
if not cliente.conectado:
    nome = st.text_input("Digite seu nome de cliente:")
    if st.button("Conectar"):
        if nome.strip():
            sucesso, msg = cliente.conectar(nome.strip())
            if sucesso:
                st.success(msg)
            else:
                st.error(msg)
        else:
            st.warning("Digite um nome válido.")
else:
    st_autorefresh(interval=3000, key="refresh")

    col1, col2 = st.columns([3, 1])

    with col2:
        st.subheader("Tópicos")
        novo_topico = st.text_input("Novo tópico:")
        if st.button("Criar Tópico") and novo_topico.strip():
            if novo_topico not in st.session_state.topicos:
                st.session_state.topicos.append(novo_topico)
                salvar_topicos(st.session_state.topicos)
                st.success(f"Tópico '{novo_topico}' criado.")

        topico_ativo = st.selectbox("Escolha um tópico", st.session_state.topicos)

        if st.button("Assinar Tópico"):
            enviar_sub(cliente, topico_ativo)
            st.success(f"Inscrito em '{topico_ativo}'")

    with col1:
        if topico_ativo:
            st.subheader(f"Chat - Tópico: {topico_ativo}")
            mensagens = st.session_state.mensagens_por_topico.get(topico_ativo, [])
            if not mensagens:
                st.info("Nenhuma mensagem ainda.")
            else:
                for msg in mensagens:
                    st.markdown(f"✅ {msg}")

            st.markdown("---")
            with st.form("formulario_envio", clear_on_submit=True):
                texto = st.text_input("Digite sua mensagem")
                enviar = st.form_submit_button("Enviar")
                if enviar and texto.strip():
                    agora = datetime.now().strftime("%H:%M")
                    mensagem_formatada = f"{cliente.nome_cliente}: {texto.strip()} [{agora}]"
                    pacote = json.dumps({
                        "tipo": "publicar",
                        "topico": topico_ativo,
                        "mensagem": texto.strip(),
                        "id": cliente.nome_cliente
                    })
                    cliente.socket.send(pacote.encode())

                    agora = datetime.now().strftime("%H:%M")
                    msg_formatada = f"{cliente.nome_cliente}: {texto.strip()} [{agora}]"
                    st.session_state.mensagens_por_topico.setdefault(topico_ativo, []).append(msg_formatada)

    # Atualizar mensagens recebidas
    for msg in cliente.mensagens:
        if "]" in msg:
            partes = msg.split("]", 1)
            topico_msg = partes[0].strip("[]")
            conteudo = partes[1].strip()
            st.session_state.mensagens_por_topico.setdefault(topico_msg, []).append(conteudo)
    cliente.mensagens.clear()
    