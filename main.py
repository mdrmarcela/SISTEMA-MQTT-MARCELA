import streamlit as st
from client import ClienteWeb
from streamlit_autorefresh import st_autorefresh


st.set_page_config(page_title="Redes Chat", layout="wide")

st.title("💬 Redes Chat - Publish/Subscribe")

# Estado do cliente
if "cliente" not in st.session_state:
    st.session_state.cliente = ClienteWeb()

if "topicos_interface" not in st.session_state:
    st.session_state.topicos_interface = []

if "mensagens_por_topico" not in st.session_state:
    st.session_state.mensagens_por_topico = {}

cliente = st.session_state.cliente


# Tela de conexão
if not cliente.conectado:
    st.subheader("Conectar ao Broker")

    nome = st.text_input("Digite o nome do cliente:")

    if st.button("Conectar"):
        if nome.strip():
            sucesso, mensagem = cliente.conectar(nome.strip())

            if sucesso:
                st.success(mensagem)
                st.rerun()
            else:
                st.error(mensagem)
        else:
            st.warning("Digite um nome válido.")

else:
    # Atualiza a tela a cada 2 segundos
    st_autorefresh(interval=2000, key="atualizar_tela")

    st.success(f"Cliente conectado: {cliente.nome_cliente}")

    col_chat, col_lateral = st.columns([3, 1])

    # Parte lateral: tópicos
    with col_lateral:
        st.subheader("Tópicos")

        novo_topico = st.text_input("Novo tópico:")

        if st.button("Criar tópico"):
            if novo_topico.strip():
                sucesso, mensagem = cliente.criar_topico(novo_topico.strip())

                if sucesso:
                    if novo_topico.strip() not in st.session_state.topicos_interface:
                        st.session_state.topicos_interface.append(novo_topico.strip())

                    st.success(mensagem)
                else:
                    st.error(mensagem)
            else:
                st.warning("Digite o nome do tópico.")

        if st.button("Atualizar tópicos"):
            cliente.listar_topicos()

        # Se o cliente recebeu tópicos do broker, atualiza a interface
        if cliente.topicos:
            st.session_state.topicos_interface = cliente.topicos

        if st.session_state.topicos_interface:
            topico_ativo = st.selectbox(
                "Escolha um tópico:",
                st.session_state.topicos_interface
            )

            if st.button("Inscrever no tópico"):
                sucesso, mensagem = cliente.inscrever(topico_ativo)

                if sucesso:
                    st.success(mensagem)
                else:
                    st.error(mensagem)
        else:
            topico_ativo = None
            st.info("Nenhum tópico criado ainda.")

    # Processa mensagens recebidas do cliente
    for msg in cliente.mensagens:
        if msg.startswith("["):
            partes = msg.split("]", 1)
            topico_msg = partes[0].replace("[", "").strip()
            conteudo = partes[1].strip()

            st.session_state.mensagens_por_topico.setdefault(
                topico_msg, []
            ).append(conteudo)

    cliente.mensagens.clear()

    # Parte principal: chat
    with col_chat:
        if topico_ativo:
            st.subheader(f"Chat do tópico: {topico_ativo}")

            mensagens = st.session_state.mensagens_por_topico.get(
                topico_ativo, []
            )

            if mensagens:
                for mensagem in mensagens:
                    st.markdown(f"**{mensagem}**")
            else:
                st.info("Nenhuma mensagem recebida nesse tópico ainda.")

            st.markdown("---")

            with st.form("formulario_mensagem", clear_on_submit=True):
                texto = st.text_input("Digite sua mensagem:")
                enviar = st.form_submit_button("Enviar")

                if enviar:
                    if texto.strip():
                        sucesso, mensagem = cliente.publicar(
                            topico_ativo,
                            texto.strip()
                        )

                        if sucesso:
                            mensagem_local = f"{cliente.nome_cliente}: {texto.strip()}"
                            st.session_state.mensagens_por_topico.setdefault(
                                topico_ativo, []
                            ).append(mensagem_local)

                            st.success("Mensagem enviada.")
                        else:
                            st.error(mensagem)
                    else:
                        st.warning("Digite uma mensagem antes de enviar.")
        else:
            st.info("Crie ou escolha um tópico para começar.")