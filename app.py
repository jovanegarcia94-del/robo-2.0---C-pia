from flask import Flask, render_template, request, redirect, session, jsonify
from iqoptionapi.stable_api import IQ_Option
from catalogador import catag
from datetime import datetime
import threading
import time
import os

app = Flask(__name__)
app.secret_key = os.urandom(24) # Gera uma chave única para cada reinicialização do servidor

# DICIONÁRIO PARA SEPARAR CADA UTILIZADOR PELO EMAIL
# Estrutura: { "email@teste.com": { "api": obj, "rodando": False, "config": {...}, ... } }
USERS = {}

def bot_loop(user_email):
    """
    Motor do Robô: Lógica Sniper mantida 100% fiel ao Robo_Trader.py
    """
    while True:
        user = USERS.get(user_email)
        if not user or not user.get("api"):
            break # Se o utilizador deslogar ou não existir, para a thread
            
        if user["rodando"]:
            try:
                api = user["api"]
                conf = user["config"]
                
                # Verificação de Stops (Gerido por utilizador)
                if user["lucro"] >= float(conf["stop_win"]):
                    user["status_texto"] = "META ATINGIDA ✅"
                    user["rodando"] = False
                    continue
                if user["lucro"] <= -float(conf["stop_loss"]):
                    user["status_texto"] = "STOP LOSS ATINGIDO ❌"
                    user["rodando"] = False
                    continue

                estrat_nome = conf["estrategia_selecionada"]
                user["status_texto"] = f"Analisando {estrat_nome}..."
                
                # Catalogação Sniper
                lista, _ = catag(api)
                melhor_par = next((item[1] for item in lista if item[0] == estrat_nome), None)

                if melhor_par and user["rodando"]:
                    ativo = melhor_par
                    user["ativo_atual"] = ativo

                    # Configurações de Timeframe conforme Robo_Trader.py
                    if estrat_nome == "MHI": tf, qnt, idx = 1, 3, 1
                    elif estrat_nome == "Torres Gêmeas": tf, qnt, idx = 1, 4, 2
                    else: tf, qnt, idx = 5, 3, 3 # MHI M5

                    # --- LÓGICA SNIPER DE ENTRADA (MANTIDA INTACTA) ---
                    timestamp = api.get_server_timestamp()
                    minutos = float(datetime.fromtimestamp(timestamp).strftime('%M.%S'))
                    
                    entrar = False
                    if idx == 1: entrar = (minutos >= 4.58 and minutos <= 5.00) or (minutos >= 9.58)
                    elif idx == 2: entrar = (minutos >= 3.58 and minutos <= 4.00) or (minutos >= 8.58 and minutos <= 9.00)
                    elif idx == 3: entrar = (minutos >= 29.58 and minutos <= 30.00) or (minutos >= 59.58)

                    if entrar:
                        user["status_texto"] = f"Sinal detectado em {ativo}!"
                        velas = api.get_candles(ativo, tf * 60, qnt, timestamp)
                        
                        if velas and not isinstance(velas, dict):
                            cores = ['Verde' if v['open'] < v['close'] else 'Vermelha' if v['open'] > v['close'] else 'Doji' for v in velas]
                            
                            direcao = None
                            if idx in [1, 3]: # Lógica MHI
                                if 'Doji' not in cores:
                                    verdes, vermelhas = cores.count('Verde'), cores.count('Vermelha')
                                    direcao = 'put' if verdes > vermelhas else 'call'
                            elif idx == 2: # Lógica Torres Gêmeas
                                direcao = 'call' if cores[0] == 'Verde' else 'put' if cores[0] == 'Vermelha' else None

                            if direcao and user["rodando"]:
                                # Execução de Entradas e Martingale
                                valor_base = float(conf["valor_entrada"])
                                gales = int(conf["niveis_martingale"]) if conf["usar_martingale"] == "S" else 0
                                
                                valor_atual = valor_base
                                for gale in range(gales + 1):
                                    if not user["rodando"]: break
                                    
                                    user["status_texto"] = f"Operando {direcao.upper()} (Gale {gale})"
                                    check, id = api.buy_digital_spot_v2(ativo, valor_atual, direcao, tf)

                                    if check:
                                        status, res = False, 0
                                        while not status:
                                            if not user["rodando"]: break
                                            status, res = api.check_win_digital_v2(id)
                                            time.sleep(0.5)
                                        
                                        user["lucro"] += res
                                        user["saldo_atual"] = api.get_balance()
                                        
                                        if res > 0:
                                            user["vitorias"] += 1
                                            user["ultima_acao"] = f"WIN {ativo} (+${res:.2f})"
                                            break # Sucesso no Gale
                                        else:
                                            user["derrotas"] += 1
                                            if gale < gales:
                                                user["ultima_acao"] = f"LOSS. Indo Gale {gale+1}"
                                                valor_atual *= float(conf["fator_martingale"])
                                            else:
                                                user["ultima_acao"] = f"LOSS FINAL em {ativo}"
                                    else:
                                        user["status_texto"] = "Erro: Payout Indisponível"
                                        break
                                
                                # Atualiza Winrate
                                total = user["vitorias"] + user["derrotas"]
                                if total > 0: user["win_rate"] = f"{(user['vitorias']/total)*100:.1f}%"
                                time.sleep(120) # Pausa pós-trade conforme original
            except Exception as e:
                print(f"Erro no motor do user {user_email}: {e}")
        time.sleep(1)

# --- ROTAS FLASK ---

@app.route("/")
def index():
    if "user_email" in session: return redirect("/dashboard")
    return render_template("login.html")

@app.route("/", methods=["POST"])
def login_post():
    email = request.form.get("email")
    senha = request.form.get("senha")
    conta = request.form.get("conta", "PRACTICE")
    
    api = IQ_Option(email, senha)
    check, reason = api.connect()
    
    if check:
        api.change_balance(conta)
        # Inicializa o espaço isolado deste utilizador
        USERS[email] = {
            "api": api,
            "rodando": False,
            "lucro": 0.0,
            "saldo_atual": api.get_balance(),
            "status_texto": "Aguardando Início",
            "ultima_acao": "Nenhum sinal operado",
            "ativo_atual": "-",
            "vitorias": 0,
            "derrotas": 0,
            "win_rate": "0%",
            "config": {
                "valor_entrada": 2.0, "stop_win": 10.0, "stop_loss": 10.0,
                "usar_martingale": "S", "niveis_martingale": 1, "fator_martingale": 2.2,
                "estrategia_selecionada": "MHI"
            }
        }
        session["user_email"] = email
        # Inicia a thread específica para este utilizador
        threading.Thread(target=bot_loop, args=(email,), daemon=True).start()
        return redirect("/dashboard")
    
    return render_template("login.html", erro="Falha no login: " + str(reason))

@app.route("/dashboard")
def dashboard():
    email = session.get("user_email")
    if not email or email not in USERS: return redirect("/")
    user = USERS[email]
    return render_template("dashboard.html", config=user["config"], saldo=user["saldo_atual"], lucro=user["lucro"])

@app.route("/status")
def status():
    email = session.get("user_email")
    if not email or email not in USERS: return jsonify({"error": "unauthorized"})
    u = USERS[email]
    return jsonify({
        "saldo": u["saldo_atual"], "lucro": u["lucro"], "rodando": u["rodando"],
        "status": u["status_texto"], "ultima": u["ultima_acao"], "winrate": u["win_rate"],
        "ativo": u["ativo_atual"]
    })

@app.route("/salvar_config", methods=["POST"])
def salvar_config():
    email = session.get("user_email")
    if email in USERS:
        USERS[email]["config"].update(request.json)
    return jsonify({"status": "ok"})

@app.route("/start")
def start():
    email = session.get("user_email")
    if email in USERS: USERS[email]["rodando"] = True
    return "ok"

@app.route("/stop")
def stop():
    email = session.get("user_email")
    if email in USERS: USERS[email]["rodando"] = False
    return "ok"

@app.route("/logout")
def logout():
    email = session.pop("user_email", None)
    if email in USERS: USERS.pop(email) # Remove a conexão do servidor ao sair
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
