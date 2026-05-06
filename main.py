import streamlit as st
from client import ClienteWeb
from streamlit_autorefresh import st_autorefresh
from datetime import datetime


st.set_page_config(
    page_title="Redes Chat",
    page_icon="💬",
    layout="wide"
)

st.markdown("""
<style>
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    .titulo-principal {
        font-size: 34px;
        font-weight: 800;
        color: #1f2937;
        margin-bottom: 0px;
    }

    .subtitulo {
        font-size: 16px;
        color: #6b7280;
        margin-bottom: 25px;
    }

    .status-conectado {
        background-color: #dcfce7;
        color: #166534;
        padding: 12px 18px;
        border-radius: 12px;
        font-weight: 600;
        margin-bottom: 20px;
    }

    .mensagem {
        background-color: #eef2ff;
        padding: 12px 16px;
        border-radius: 14px;
        margin-bottom: 10px;
        color: #1f2937;
        font-size: 15px;
        border-left: 5px solid #4f46e5;
    }

    .topico-tag {
        background-color: #dbeafe;
        color: #1e40af;
        padding: 6px 10px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        display: inline-block;
        margin-bottom: 12px;
    }

    .aviso-inscricao {
        background-color: #fef3c7;
        color: #92400e;
        padding: 12px 16px;
        border-radius: 12px;
        font-weight: 600;
        margin-top: 10px;
        margin-bottom: 10px;
    }

    div.stButton > button {
        width: 100%;
        border-radius: 10px;
        border: none;
        background-color: #2563eb;
        color: white;
        font-weight: 600;
        padding: 10px;
    }

    div.stButton > button:hover {
        background-color: #1d4ed8;
        color: white;
    }

    div.stFormSubmitButton > button {
        width: 100%;
        border-radius: 10px;
        border: none;
        background-color: #16a34a;
        color: white;
        font-weight: 600;
        padding: 10px;
    }

    div.stFormSubmitButton > button:hover {
        background-color: #15803d;
        color: white;
    }
</style>
""", unsafe_allow_html=True)


# Estados da aplicação
if "cliente" not in st.session_state:
    st.session_state.cliente = ClienteWeb()

if "topicos_interface" not in st.session_state:
    st.session_state.topicos_interface = []

if "mensagens_por_topico" not in st.session_state:
    st.session_state.mensagens_por_topico = {}

if "topicos_inscritos" not in st.session_state:
    st.session_state.topicos_inscritos = []

if "mensagens_sistema" not in st.session_state:
    st.session_state.mensagens_sistema = []


cliente = st.session_state.cliente

# Garante que o atributo exista no cliente
if not hasattr(cliente, "topicos_desinscritos"):
    cliente.topicos_desinscritos = []


# Cabeçalho
st.markdown(
    """
    <div class="titulo-principal">Redes Chat</div>
    <div class="subtitulo">
        Sistema de comunicação no modelo Publish/Subscribe com Broker e Clientes
    </div>
    """,
    unsafe_allow_html=True
)


# Tela de conexão
if not cliente.conectado:
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.subheader("Conectar ao Broker")
        st.write("Digite um nome para identificar este cliente na rede.")

        nome = st.text_input(
            "Nome do cliente:",
            placeholder="Exemplo: Cliente1"
        )

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
    st_autorefresh(interval=2000, key="atualizar_tela")

    st.markdown(
        f"""
        <div class="status-conectado">
            Cliente conectado: {cliente.nome_cliente}
        </div>
        """,
        unsafe_allow_html=True
    )

    # Atualiza lista de tópicos recebida do broker
    if cliente.topicos:
        st.session_state.topicos_interface = cliente.topicos

    # Processa mensagens recebidas do cliente
    for msg in cliente.mensagens:
        if msg.startswith("[") and "]" in msg:
            partes = msg.split("]", 1)
            topico_msg = partes[0].replace("[", "").strip()
            conteudo = partes[1].strip()

            st.session_state.mensagens_por_topico.setdefault(
                topico_msg, []
            ).append(conteudo)
        else:
            st.session_state.mensagens_sistema.append(msg)

    cliente.mensagens.clear()

    # Atualiza a interface apenas quando o broker confirmar que saiu do tópico
    for topico in cliente.topicos_desinscritos:
        if topico in st.session_state.topicos_inscritos:
            st.session_state.topicos_inscritos.remove(topico)

    cliente.topicos_desinscritos.clear()

    topico_ativo = None

    col_chat, col_lateral = st.columns([3, 1])

    # Lateral: tópicos
    with col_lateral:
        st.subheader("Tópicos")

        novo_topico = st.text_input(
            "Criar novo tópico:",
            placeholder="Exemplo: avisos"
        )

        if st.button("Criar tópico"):
            if novo_topico.strip():
                topico = novo_topico.strip()

                sucesso, mensagem = cliente.criar_topico(topico)

                if sucesso:
                    if topico not in st.session_state.topicos_interface:
                        st.session_state.topicos_interface.append(topico)

                    # Quem cria o tópico já fica inscrito nele
                    if topico not in st.session_state.topicos_inscritos:
                        st.session_state.topicos_inscritos.append(topico)

                    st.success(mensagem)
                    st.rerun()
                else:
                    st.error(mensagem)
            else:
                st.warning("Digite o nome do tópico.")

        if st.button("Atualizar tópicos"):
            resultado = cliente.listar_topicos()

            if isinstance(resultado, tuple):
                st.info(resultado[1])
            else:
                st.info("Solicitação enviada ao broker.")

        st.divider()

        if st.session_state.topicos_interface:
            topico_ativo = st.selectbox(
                "Escolha um tópico:",
                st.session_state.topicos_interface
            )

            inscrito = topico_ativo in st.session_state.topicos_inscritos

            if inscrito:
                st.success("Você está inscrito neste tópico.")

                if st.button("Sair do tópico"):
                    sucesso, mensagem = cliente.desinscrever(topico_ativo)

                    if sucesso:
                        st.info("Solicitação para sair enviada ao broker.")
                    else:
                        st.error(mensagem)

            else:
                st.warning("Você ainda não está inscrito neste tópico.")

                if st.button("Inscrever no tópico"):
                    sucesso, mensagem = cliente.inscrever(topico_ativo)

                    if sucesso:
                        if topico_ativo not in st.session_state.topicos_inscritos:
                            st.session_state.topicos_inscritos.append(topico_ativo)

                        st.success(mensagem)
                        st.rerun()
                    else:
                        st.error(mensagem)

        else:
            st.info("Nenhum tópico criado ainda.")

        if st.session_state.mensagens_sistema:
            st.divider()
            st.caption("Avisos do sistema")

            for aviso in st.session_state.mensagens_sistema[-3:]:
                st.info(aviso)

    # Principal: chat
    with col_chat:
        if topico_ativo:
            st.markdown(
                f'<div class="topico-tag">Tópico ativo: {topico_ativo}</div>',
                unsafe_allow_html=True
            )

            st.subheader("Mensagens")

            mensagens = st.session_state.mensagens_por_topico.get(
                topico_ativo, []
            )

            if mensagens:
                for mensagem in mensagens:
                    st.markdown(
                        f'<div class="mensagem">{mensagem}</div>',
                        unsafe_allow_html=True
                    )
            else:
                st.info("Nenhuma mensagem recebida nesse tópico ainda.")

            st.divider()

            inscrito = topico_ativo in st.session_state.topicos_inscritos

            if not inscrito:
                st.markdown(
                    """
                    <div class="aviso-inscricao">
                        Não é possível enviar mensagem em tópicos que você não é inscrito.
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            else:
                with st.form("formulario_mensagem", clear_on_submit=True):
                    texto = st.text_input(
                        "Digite sua mensagem:",
                        placeholder="Escreva uma mensagem para o tópico..."
                    )

                    enviar = st.form_submit_button("Enviar mensagem")

                    if enviar:
                        if texto.strip():
                            sucesso, mensagem = cliente.publicar(
                                topico_ativo,
                                texto.strip()
                            )

                            if sucesso:
                                hora = datetime.now().strftime("%H:%M")
                                mensagem_local = (
                                    f"{cliente.nome_cliente}: {texto.strip()} [{hora}]"
                                )

                                st.session_state.mensagens_por_topico.setdefault(
                                    topico_ativo, []
                                ).append(mensagem_local)

                                st.success("Mensagem enviada.")
                                st.rerun()
                            else:
                                st.error(mensagem)
                        else:
                            st.warning("Digite uma mensagem antes de enviar.")

        else:
            st.subheader("Bem-vindo ao Redes Chat")
            st.info("Crie ou escolha um tópico para começar.")