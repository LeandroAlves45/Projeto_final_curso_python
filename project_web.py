from flask import Flask, flash, render_template, request, redirect, url_for, session
import sqlite3
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import re
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

"""
project_web.py

Aplicação Flask para gerenciamento de reservas de carros:
- Conexão com SQLite para persistência de usuários, carros, reservas e pagamentos.
- Rotas para login, cadastro, listagem de carros, CRUD de reservas e processamento de pagamento.
- Uso de sessões para controle de autenticação e totais de pagamento.
"""


#criar base de dados no sqlite (primeiro passo)
app = Flask(__name__)
app.secret_key= 'chave_super_secreta_444'   #Usada para criptografar cookies da sessão
app.config["DEBUG"] = True              #Modo Debug habilitado

#filtro para converter string de data para objeto date
@app.template_filter('todate')
def todate_filter(value, format="%Y-%m-%d"):
    """
    Converte string no formato YYYY-MM-DD para objeto date do Python.
    Uso em Jinja: {{ '2025-05-01'|todate }} retorna datetime.date(2025, 5, 1).
    """
    try:
        return datetime.strptime(value,format).date()
    except:
        return value

#conectar base de dados ao projeto
def conectar_bd():
    conn = sqlite3.connect("database/banco_de_dados.db")
    conn.row_factory = sqlite3.Row
    return conn

#criação das tabelas da base de dados
def criar_tabelas():
     #Cria as tabelas no banco SQLite caso não existam:
     #- usuarios (login e senha)
     #- carros (modelo, categoria, preço etc.)
     #- reservas (relaciona usuário, carro e datas)
     #- pagamentos (dados de cartão vinculados à reserva)
     
    conn= conectar_bd()
    cursor= conn.cursor()
    cursor.executescript('''
                        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            usuario TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS veiculos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            marca TEXT NOT NULL,
            modelo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            transmissao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            capacidade INTEGER NOT NULL,
            imagem TEXT NOT NULL,
            valor_diaria REAL NOT NULL,
            ultima_revisao DATE NOT NULL,
            proxima_revisao DATE NOT NULL,
            ultima_inspecao DATE NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            veiculo_id INTEGER NOT NULL,
            data_inicio DATE NOT NULL,
            data_fim DATE NOT NULL,
            valor_total REAL NOT NULL,
            status TEXT DEFAULT 'Ativa',
            FOREIGN KEY (cliente_id) REFERENCES clientes(id),
            FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
        );
        
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reserva_id INTEGER NOT NULL,
            numero_cartao TEXT NOT NULL,
            nome_cartao TEXT NOT NULL,
            validade TEXT NOT NULL,
            codigo_seg INTEGER NOT NULL,
            FOREIGN KEY (reserva_id) REFERENCES reservas(id)
        );
    ''')
    conn.commit()
    conn.close()

#Vamos agora criar uma função para verificar se existe o usuário
def verificar_usuario(usuario, senha):
 #Valida credenciais de login.
    
#Args:
    #usuario (str): nome de usuário.
    #senha (str): senha em texto plano.
    
#Returns:
    #dict | None: dados do usuário (id, nome) se válido, ou None caso contrário.

    conn= conectar_bd()
    cursor=conn.cursor()
    cursor.execute("SELECT * FROM clientes WHERE usuario = ? AND senha = ?", (usuario,senha))
    usuario_encontrado= cursor.fetchone()
    conn.close()
    return usuario_encontrado

#função para registar um novo utilizador
def registar_usuario(nome, usuario, senha):
    conn= conectar_bd()
    cursor= conn.cursor()
    cursor.execute("INSERT INTO clientes (nome, usuario, senha) VALUES (?, ?, ?)", (nome, usuario, senha))
    conn.commit()
    conn.close()

#página inicial (login/registo)
@app.route('/', methods=  ['GET','POST'])
def home ():
    mensagem = None #mensagem de erro se existir
    #Na página de login/registo vamos verificar se todos os requisitos são preenchidos
    if request.method == "POST":    
        if 'nome' in request.form and 'senha_confirmacao' in request.form:
            nome= request.form['nome']
            usuario = request.form ['usuario']
            senha =request.form ['senha']
            senha_confirmacao=request.form['senha_confirmacao']

            if senha != senha_confirmacao:
                mensagem= "As senhas não coincidem."

            else: 
                try:
                    conn =conectar_bd()
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO clientes (nome, usuario, senha) VALUES (?,?,?)", (nome,usuario, senha))
                    conn.commit()
                    conn.close()
                    mensagem= "Registo efetuado com sucesso! Agora podes realizar o login."
                except sqlite3.IntegrityError:
                    mensagem= "Este nome do usuário ja se encontra registado."
    if 'usuario' in request.form and 'senha' in request.form:
        usuario= request.form['usuario']
        senha= request.form['senha']

        usuario_encontrado= verificar_usuario(usuario,senha)
        if usuario_encontrado:
            session['usuario'] = usuario_encontrado[2] #guarda o nome do usuário na sessão
            return redirect(url_for('listar_carros')) #Redireciona para a página listar_carros após executar login
            
        else:
            mensagem = "Credenciais inválidas, tente novamente."
            
    return render_template('index.html', mensagem=mensagem)


#Página com todos os carros
@app.route('/carros', methods=['GET']) #define a rota da página
def listar_carros():
    #Verificar se o utilizador está autenticado
    if 'usuario' not in session:
        return redirect(url_for('home'))
    #obtem a data de hoje
    hoje = date.today().isoformat()
    #calcula a data daqui a 1 ano para o filtro de inspeção obrigatório
    um_ano = (date.today() + relativedelta(years=1)).isoformat()
    
    #conectar á base de dados
    conn= conectar_bd()
    cursor = conn.cursor()

    # Monta a query principal com filtros de inspeção e revisão e exclusão de veículos reservados
    sql_base = '''
    SELECT v.*
    FROM veiculos v
    WHERE v.id NOT IN (
        SELECT r.veiculo_id
        FROM reservas r
        WHERE date(r.data_fim) >= DATE('now')
            AND r.status = 'Ativa'
        )
    '''
    parametros = []


    #Recolher os filtros enviados por GET (pesquisa e filtros laterais)
    pesquisa= request.args.get('pesquisa', "").strip()

    if pesquisa:
         # Adiciona filtro de pesquisa por marca, modelo, categoria, tipo e transmissão
        sql_base += """
            AND (LOWER(v.marca) LIKE ?
              OR LOWER(v.modelo) LIKE ?
              OR LOWER(v.categoria) LIKE ?
              OR LOWER(v.tipo) LIKE ?
              OR LOWER(v.transmissao) LIKE ?
              OR LOWER(v.valor_diaria) LIKE ?)
        """
        pesquisa_like = f'%{pesquisa}%'
        parametros.extend([pesquisa_like, pesquisa_like, pesquisa_like, pesquisa_like, pesquisa_like, pesquisa_like])

    # Executa a query final com placeholders para evitar SQL injection
    cursor.execute(sql_base, tuple(parametros))
    carros = cursor.fetchall()
    conn.close()

    # Renderiza template passando lista filtrada de carros e termo de pesquisa
    return render_template('carros.html', carros=carros, pesquisa=pesquisa)
#Função vou inserir os carros para o utilizador ter acesso
def inserir_carros():
    conn = conectar_bd()
    cursor = conn.cursor()

    #Verificar se já existem carros, para não correr o risco de ficarem duplicados
    cursor.execute("SELECT COUNT (*) FROM veiculos")
    total= cursor.fetchone()[0]

    if total > 0:
        conn.close()
        return #já existem carros

    carros = [
         # marca, modelo, categoria, transmissao, tipo, capacidade, imagem, valor_diaria, ultima_revisao, proxima_revisao, ultima_inspecao
        ("Toyota", "Yaris", "Carro Pequeno", "Manual", "Carro", 4, "yaris.jpg", 30.0, "2024-01-10", "2025-01-10", "2024-02-10"),
        ("Honda", "Civic", "Carro Médio", "Automática", "Carro", 5, "civic.jpg", 45.0, "2024-01-05", "2025-01-05", "2024-02-01"),
        ("BMW", "X5", "Carro SUV", "Automática", "Carro", 5, "bmw_x5.jpg", 120.0, "2023-08-01", "2024-08-01", "2023-09-01"),
        ("Audi", "A8", "Carros Luxo", "Automática", "Carro", 5, "audi_a8.jpg", 160.0, "2024-01-15", "2025-01-15", "2024-01-20"),
        ("Fiat", "500", "Carro Pequeno", "Manual", "Carro", 4, "fiat_500.jpg", 28.0, "2024-02-01", "2025-02-01", "2024-02-10"),
        ("Kawasaki", "Ninja 400", "Mota Média", "Manual", "Mota", 2, "ninja_400.jpg", 40.0, "2024-03-01", "2025-03-01", "2024-03-10"),
        ("Yamaha", "TMAX", "Mota Grande", "Automática", "Mota", 2, "tmax.jpg", 50.0, "2024-01-20", "2025-01-20", "2024-02-01")
    ]

    cursor.executemany('''
        INSERT INTO veiculos (
            marca, modelo, categoria, transmissao, tipo, capacidade, imagem, valor_diaria,
            ultima_revisao, proxima_revisao, ultima_inspecao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', carros)

    conn.commit()
    conn.close()



@app.route("/reservar/<int:carro_id>", methods=["GET", "POST"])
def reservar_carro(carro_id):

#Rota para mostrar o formulário de reserva (GET) e processar a reserva (POST).
#Em GET: busca sempre o carro pelo ID e exibe o template.
#Em POST: valida datas, obtém cliente, calcula total, cria reserva e redireciona ao pagamento.
     
    if 'usuario' not in session:
        return redirect(url_for('home'))
    
    conn = conectar_bd()
    cursor = conn.cursor()

# Busca o carro no GET para preencher template e no POST para cálculo
    cursor.execute("SELECT * FROM veiculos WHERE id = ?", (carro_id,))
    carro = cursor.fetchone()
    if not carro:
        conn.close()
        return "Carro não encontrado", 404
    
    if request.method == "POST":
        data_inicio_str = request.form['data_inicio']
        data_fim_str = request.form['data_fim']
        usuario = session['usuario']

        # Converte para datetime.date
        data_inicio = datetime.strptime(data_inicio_str, "%Y-%m-%d").date()
        data_fim = datetime.strptime(data_fim_str, "%Y-%m-%d").date()

        # Validação: fim não pode ser antes de início
        if data_fim < data_inicio:
            conn.close()
            return "A data de fim não pode ser anterior à data de início.", 400

        # Busca ID do cliente
        cursor.execute("SELECT id FROM clientes WHERE usuario = ?", (usuario,))
        cliente = cursor.fetchone()
        if not cliente:
            conn.close()
            return f"Cliente não encontrado para o usuário {usuario}.", 404
        cliente_id = cliente['id']

        # Calcula dias e total
        dias = (data_fim - data_inicio).days + 1
        valor_diaria = carro['valor_diaria']
        total = dias * valor_diaria

        # Insere reserva
        cursor.execute("""
            INSERT INTO reservas 
                (cliente_id, veiculo_id, data_inicio, data_fim, valor_total, status)
            VALUES (?, ?, ?, ?, ?, 'Ativa')
        """, (cliente_id, carro_id, data_inicio_str, data_fim_str, total))
        conn.commit()
        reserva_id = cursor.lastrowid

        # Armazena o total a pagar na sessão para exibir no pagamento
        session['total_a_pagar'] = total
        #'total_a_pagar': valor calculado da reserva que será exibido na página de pagamento.
        # Certifica-se de remover qualquer diferença pré-existente
        session.pop('diferenca_pagamento', None)

        conn.close()
        # Redireciona para a tela de pagamento
        return redirect(url_for('pagamento', reserva_id=reserva_id))

    conn.close()
    return render_template("reserva.html", carro=carro)

#Rota de pagamento após uma reserva
@app.route('/pagamento/<int:reserva_id>', methods=['GET', 'POST'])
def pagamento(reserva_id):

    """
    Rota para exibir valores e processar o pagamento:
    - Usa session['total_a_pagar'] e, se existir >0, session['diferenca_pagamento'].
    - Ao concluir (POST), insere em pagamentos e limpa ambas as chaves na sessão.
    """

    if 'usuario' not in session:
        return redirect(url_for('home'))
    
    conn = conectar_bd()
    cursor = conn.cursor()

    # Recupera apenas o mínimo de dados da reserva (pode ser usado para validação extra)
    cursor.execute("SELECT id FROM reservas WHERE id = ?", (reserva_id,))
    if not cursor.fetchone():
        conn.close()
        return "Reserva não encontrada.", 404

    # Carrega valores da sessão
    valor_total = session.get('total_a_pagar', 0)
    diferenca = session.get('diferenca_pagamento', 0)
    mostrar_alteracao = (diferenca > 0)

    #Verifica se o formulário foi submetido
    if request.method == 'POST':
        #Recolhe e limpa os dados do formulário
        numero_cartao = re.sub(r'\D', '', request.form.get('numero_cartao', ''). strip())
        nome_cartao = request.form.get('nome_cartao', '').strip()
        validade= request.form.get('validade', '').strip() #espera "YYYY-MM"
        codigo_seg = request.form.get('codigo_seg', '').strip()

        #validação do número do cartão
        if not re.fullmatch(r'\d{13}|\d{15}', numero_cartao):
            flash('Número do cartão inválido: deve ter 13 ou 15 dígitos.', 'error')
            conn.close()
            return redirect(url_for('pagamento', reserva_id=reserva_id))
         #validação do nome (apenas letras e espaços)
        if not re.fullmatch(r"[A-Za-zÀ-ÿ ]+", nome_cartao):
            flash('Nome no cartão inválido: apenas letras e espaços são permitidos.', 'error')
            conn.close()
            return redirect(url_for('pagamento', reserva_id=reserva_id))

        #validação da validade (formato e não expirado)
        try:
            ano, mes = map(int, validade.split('-'))
            # considera válido todo o mês: compara primeiro dia do mês
            if date(ano, mes, 1) < date.today().replace(day=1):
                flash('Data de expiração já passou.', 'error')
                conn.close()
                return redirect(url_for('pagamento', reserva_id=reserva_id))
        except ValueError:
            flash('Formato de data de expiração inválido.', 'error')
            conn.close()
            return redirect(url_for('pagamento', reserva_id=reserva_id))

        #validação do código de segurança (3 ou 4 dígitos)
        if not re.fullmatch(r'\d{3,4}', codigo_seg):
            flash('CVV inválido: deve ter 3 ou 4 dígitos.', 'error')
            conn.close()
            return redirect(url_for('pagamento', reserva_id=reserva_id))

        #insere os dados do pagamento
        cursor.execute("""
            INSERT INTO pagamentos (reserva_id, numero_cartao, nome_cartao, validade, codigo_seg)
            VALUES (?, ?, ?, ?, ?)
        """, (reserva_id, numero_cartao, nome_cartao, validade, codigo_seg))
        conn.commit()

        #limpar a diferença da sessão após o pagamento
        session.pop('diferenca_pagamento', None)
        session.pop('total_a_pagar', None)

        conn.close()
        #mostra a mensagem e redireciona o utilizador para a página "minhas_reservas"
        flash ('Pagamento realizado com sucesso!', 'sucess')
        #Mensagem de confirmação de reserva, categoria 'success' para estilização no template.
        return redirect(url_for('minhas_reservas'))

    conn.close()
    #Se for pedido GET, mostra o formulário de pagamento
    return render_template('pagamento.html', reserva_id=reserva_id, valor_total= valor_total, mostrar_alteracao=mostrar_alteracao, valor_alteracao=diferenca)

@app.route("/minhas_reservas")
def minhas_reservas():
    if 'usuario' not in session:
        return redirect(url_for('home')) #se não estiver logado
    
    usuario = session['usuario']
    conn= conectar_bd()
    cursor = conn.cursor()

    #Obter ID do cliente com base no nome do utilizador da sessão
    cursor.execute("SELECT id FROM clientes WHERE usuario = ?", (usuario,))
    cliente= cursor.fetchone()

    if cliente:
        cliente_id = cliente[0]

        #Obter todas as reservas feitas por este cliente
        cursor.execute("""
            SELECT reservas.id, veiculos.marca, veiculos.modelo, reservas.data_inicio, reservas.data_fim, veiculos.valor_diaria, reservas.status
            FROM reservas
            JOIN veiculos ON reservas.veiculo_id = veiculos.id
            WHERE reservas.cliente_id = ?
        """, (cliente_id,))
        reservas = []
        for row in cursor.fetchall():
            id, marca, modelo, data_inicio, data_fim, valor_diaria, status = row
            dias = (datetime.strptime(data_fim, "%Y-%m-%d") - datetime.strptime(data_inicio, "%Y-%m-%d")).days + 1
            total = dias * valor_diaria
            reservas.append({
                "id": id,
                "marca": marca,
                "modelo": modelo,
                "data_inicio": data_inicio,
                "data_fim": data_fim,
                "valor_diaria": valor_diaria,
                "total": total,
                "status": status
            })
        conn.close()

        return render_template("minhas_reservas.html", reservas=reservas)
    
    conn.close()
    return redirect(url_for('home'))

#esta rota trata  do pedido de POST no botão "limpar_reservas"
@app.route('/limpar_reservas', methods=['POST'])
def limpar_reservas():
    #garantir que o usuario está iniciado
    if 'usuario' not in session:
        return redirect(url_for('home'))

    #obter o id do utilizador autenticado
    usuario= session['usuario']

    conn = conectar_bd()
    cursor = conn.cursor()
    #Buscar Id do cliente
    cursor.execute("SELECT id FROM clientes WHERE usuario = ?", (usuario,))
    cliente = cursor.fetchone()

    #o importante é apagar as reservas que não estão ativas
    if cliente:
        cliente_id = cliente[0]
        cursor.execute("DELETE FROM reservas WHERE cliente_id = ? AND status != 'Ativa'", (cliente_id,))
        conn.commit()
    
    
    conn.close()

    #enviar uma mensagem de sucesso temporária 
    flash("Reservas inativas foram removidas com sucesso com sucesso")
    return redirect(url_for('minhas_reservas'))

#rota para cancelar uma reserva especifica
@app.route("/cancelar_reserva/<int:reserva_id>")
def cancelar_reserva(reserva_id):
    if 'usuario' not in session:
        return redirect(url_for('home'))
    
    conn = conectar_bd()
    cursor = conn.cursor()

    #Atualizar o status da reserva para 'Cancelada'
    cursor.execute("UPDATE reservas SET status = 'Cancelada' WHERE id = ?", (reserva_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("minhas_reservas"))

#Rota para alterar as datas da reservas
@app.route("/alterar_reserva/<int:reserva_id>", methods= ["GET", "POST"])
def alterar_reserva(reserva_id):

    """
    Rota para exibir o form de alteração (GET) e processar mudança de datas (POST).
    - Recalcula total e diferença.
    - Armazena temporariamente em sessão: 'total_a_pagar' e, se >0, 'diferenca_pagamento'.
    - Redireciona sempre para /pagamento.
    """

    if 'usuario' not in session:
        return redirect(url_for('home'))
    
    conn = conectar_bd()
    cursor = conn.cursor()

    if request.method == "POST":
        #obter novas datas do formulário
        nova_inicio= request.form['data_inicio']
        nova_fim= request.form ['data_fim']

        #Validar ordem das datas
        data_inicio= datetime.strptime(nova_inicio, "%Y-%m-%d").date()
        data_fim= datetime.strptime(nova_fim, "%Y-%m-%d").date()

        #Verifica se a data do fim é anterior á de inicio
        if data_fim < data_inicio:
            conn.close()
            return "A data de fim não pode ser anterior á data de início!"

        # Obter dados da reserva original (veiculo e valor anterior)
        cursor.execute("SELECT veiculo_id, valor_total FROM reservas WHERE id = ?", (reserva_id,))
        dados_reserva = cursor.fetchone()

        if not dados_reserva:
            conn.close()
            return "Reserva não encontrada."
        
        veiculo_id, valor_anterior = dados_reserva['veiculo_id'], dados_reserva['valor_total']

        #Obter o valor da diária do veículo
        cursor.execute("SELECT valor_diaria FROM veiculos WHERE id = ?", (veiculo_id,))
        valor = cursor.fetchone()

        if not valor:
            conn.close()
            return "Veículo não encontrado."
        
        diaria = valor['valor_diaria']

        #calcular o novo total com base nas novas datas
        dias = (data_fim - data_inicio).days + 1
        novo_total = diaria * dias

        #calcular a diferença entre o novo total e o valor pago anteriormente
        diferenca = novo_total - valor_anterior

        #Atualizar as datas e o novo valor na reserva
        cursor.execute("""
            UPDATE reservas
            SET data_inicio = ?, data_fim = ?, valor_total = ?
            WHERE id = ?
        """, (nova_inicio, nova_fim, novo_total, reserva_id))

        conn.commit()
        # Armazena na sessão apenas o que for relevante
        session['total_a_pagar'] = novo_total
        if diferenca > 0:
            session['diferenca_pagamento'] = diferenca
        else:
            session.pop('diferenca_pagamento', None)
        
        conn.close()

        #se houver valor adicional a pagar, redireciona para a página de pagamento
        return redirect(url_for('pagamento', reserva_id=reserva_id))

    #se for um pedido GET , busca dados atuais para mostrar no formulário
    cursor.execute("""
        SELECT data_inicio, data_fim 
        FROM reservas WHERE id = ?
    """, (reserva_id,))
    reserva = cursor.fetchone()
    conn.close()

    #enviar os dados para o template
    return render_template("alterar_reserva.html", reserva = reserva, reserva_id= reserva_id)
#bloco de código necessário para atualizar as categorias
"""def atualiza_categorias():
    conn = conectar_bd()
    cursor = conn.cursor()
    cursor.execute(
    UPDATE veiculos
       SET categoria = CASE
           WHEN tipo = 'Carro' AND categoria LIKE '%Pequeno%' THEN 'Carro Pequeno'
           WHEN tipo = 'Carro' AND categoria LIKE '%Médio%'   THEN 'Carro Médio'
           WHEN tipo = 'Carro' AND categoria LIKE '%SUV%'     THEN 'Carro SUV'
           WHEN tipo = 'Carro' AND categoria LIKE '%Luxo%'    THEN 'Carro Luxo'
           WHEN tipo = 'Mota'  AND categoria LIKE '%Média%'   THEN 'Mota Média'
           WHEN tipo = 'Mota'  AND categoria LIKE '%Grande%'  THEN 'Mota Grande'
           ELSE categoria
       END
    WHERE categoria IN ('Pequeno','Médio','SUV','Luxo','Grande');
    )
    conn.commit()
    conn.close()
    print("Categorias atualizadas com sucesso!")"""
    
#route de logout, redireciona para a página "home", para o registo     
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# Garante que a pasta static/img existe
os.makedirs(os.path.join(app.static_folder, "img"), exist_ok=True)
#Criação do excel com os dados dos clientes, veiculos, reservas e formas de pagamento
#Caminho para a base de dados SQLite
DB_PATH = os.path.join(os.path.dirname(__file__), "database", "banco_de_dados.db")

#Lista das tabelas que queremos exportar
TABELAS = ["clientes", "veiculos", "reservas", "pagamentos"]

#função que retorna um pandas.DATAFRAME para cada tabela
def ler_tabela(tabela: str, conn: sqlite3.Connection) -> pd.DataFrame:
    query = f"SELECT * FROM {tabela};"
    df = pd. read_sql_query(query,conn)
    return df

def main():
    #cria a pasta "exports" se não existir
    pasta_exports = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(pasta_exports, exist_ok=True)

    #abrir a conexão SQLite
    conn = sqlite3.connect(DB_PATH)
    try:
        for tabela in TABELAS:
            print(f"Lendo a tabela '{tabela}'...")
            df = ler_tabela(tabela, conn)

            #gravar excel 
            excel_path = os.path.join(pasta_exports, f"{tabela}.xlsx")
            #para escrever XLSX, é necessário o openpyxl
            df.to_excel(excel_path, index=False, engine= "openpyxl")
            print(f"Gravado Excel em: {excel_path}")
        
        print("\nExportação concluída com sucesso!")
    finally:
        conn.close()

def ler_tabela_para_dashboard_inicial(tabela:str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(f"SELECT * FROM {tabela};", conn)
    finally:
        conn.close()
    return df

def gerar_graficos_dashboard():
    #ler todas as tabelas
    df_clientes = ler_tabela_para_dashboard_inicial("clientes")
    df_veiculos = ler_tabela_para_dashboard_inicial("veiculos")
    df_reservas = ler_tabela_para_dashboard_inicial("reservas")


    #Total de clientes
    total_clientes = len(df_clientes)

    #Total de veículos
    total_veiculos = len(df_veiculos)

    # calcular reservas ativas
    if "status" in df_reservas.columns:
        total_reservas_ativas = len(df_reservas[df_reservas["status"].str.lower() == "ativa"])
    else:
        total_reservas_ativas = 0

    # Faturação do último mês (usando data_inicio)
    #converte data_inicio para datetime
    df_reservas["data_inicio"] = pd.to_datetime(df_reservas["data_inicio"])
    hoje = pd.Timestamp.today()

     # Começo do mês atual
    mes_atual_inicio = hoje.replace(day=1)
    mask_mes_atual = df_reservas["data_inicio"] >= mes_atual_inicio
    faturacao_ultimo_mes = df_reservas.loc[mask_mes_atual, "valor_total"].sum()

    # Reservas por mês (últimos 12 meses)
    inicio_12meses = hoje - pd.DateOffset(months=11)  # data de 11 meses atrás (para totalizar 12)
    mask_12 = df_reservas["data_inicio"] >= inicio_12meses
    df_ultimas_res = df_reservas.loc[mask_12].copy()
    df_ultimas_res["ano_mes"] = df_ultimas_res["data_inicio"].dt.to_period("M")
    reservas_por_mes = (
        df_ultimas_res
        .groupby("ano_mes")
        .size()
        .reset_index(name="qtd_reservas")
    )

    # Garante que mesmo meses sem reservas apareçam com valor 0
    todos_meses = pd.period_range(
        start=inicio_12meses.to_period("M"),
        end=hoje.to_period("M"),
        freq="M"
    )
    reservas_por_mes = (
        reservas_por_mes
        .set_index("ano_mes")
        .reindex(todos_meses, fill_value=0)
        .reset_index()
        .rename(columns={"index": "ano_mes"})
    )
    reservas_por_mes["ano_mes_str"] = reservas_por_mes["ano_mes"].astype(str)

    # Faturação por mês (últimos 12 meses)
    df_ultimas_res["ano_mes"] = df_ultimas_res["data_inicio"].dt.to_period("M")
    faturacao_por_mes = (
        df_ultimas_res
        .groupby("ano_mes")["valor_total"]
        .sum()
        .reset_index()
    )
    faturacao_por_mes = (
        faturacao_por_mes
        .set_index("ano_mes")
        .reindex(todos_meses, fill_value=0)
        .reset_index()
        .rename(columns={"index": "ano_mes"})
    )
    faturacao_por_mes["ano_mes_str"] = faturacao_por_mes["ano_mes"].astype(str)

    # Gera o gráfico de Reservas por mês
    plt.figure(figsize=(8, 4))
    plt.bar(reservas_por_mes["ano_mes_str"], reservas_por_mes["qtd_reservas"], color="#007bff")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Número de Reservas")
    plt.title("Reservas nos Últimos 12 Meses")
    plt.tight_layout()
    caminho_reservas = os.path.join(app.static_folder, "img", "reservas_por_mes.png")
    plt.savefig(caminho_reservas)
    plt.close()

    # Gera o gráfico de Faturação por mês
    plt.figure(figsize=(8, 4))
    plt.plot(faturacao_por_mes["ano_mes_str"], faturacao_por_mes["valor_total"], marker="o")
    plt.xticks(rotation=45, ha="right")
    plt.ylabel("Faturação (€)")
    plt.title("Faturação Mensal (Últimos 12 Meses)")
    plt.tight_layout()
    caminho_faturacao = os.path.join(app.static_folder, "img", "faturacao_por_mes.png")
    plt.savefig(caminho_faturacao)
    plt.close()

    # Top 5 clientes por faturação (usando somente reservas)
    top5_clientes = []
    # Verifica se existem as colunas necessárias
    if {"cliente_id", "valor_total"}.issubset(df_reservas.columns):
        soma_por_cliente = (
            df_reservas
            .groupby("cliente_id")["valor_total"]
            .sum()
            .sort_values(ascending=False)
            .head(5)
            .reset_index()
        )
        # Mapeia id_cliente -> nome 
        mapa_nomes = {}
        if "nome" in df_clientes.columns and "id" in df_clientes.columns:
            mapa_nomes = df_clientes.set_index("id")["nome"].to_dict()

        for idx, row in soma_por_cliente.iterrows():
            cliente_id = row["cliente_id"]
            nome_cliente = mapa_nomes.get(cliente_id, f"Cliente {cliente_id}")
            valor_faturado = row["valor_total"]
            top5_clientes.append((idx + 1, nome_cliente, valor_faturado))

    # Retorna o dicionário com todos os indicadores para o template
    return {
        "total_clientes": total_clientes,
        "total_veiculos": total_veiculos,
        "total_reservas_ativas": total_reservas_ativas,
        "faturacao_ultimo_mes": round(float(faturacao_ultimo_mes), 2),
        "img_reservas": "img/reservas_por_mes.png",
        "img_faturacao": "img/faturacao_por_mes.png",
        "top5_clientes": top5_clientes
    }
 
#Rota dashboard com os gráficos
@app.route("/dashboard")
def dashboard():
    # Gera (ou atualiza) os gráficos e obtém os indicadores
    indicadores = gerar_graficos_dashboard()

    # Passa para o template
    return render_template("dashboard_inicial.html", **indicadores)
if __name__=='__main__':
    #Inicializa o esquema e dados padrão de carros
    criar_tabelas()
    inserir_carros()
    #atualiza_categorias() codigo necessário para atualizar as categorias
    main()
    app.run(debug=True)

