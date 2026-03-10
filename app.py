from flask import Flask, render_template, request, redirect, session, jsonify
from iqoptionapi.stable_api import IQ_Option
from catalogador import catag
from datetime import datetime
import threading
import time

app = Flask(__name__)
app.secret_key = "sniperbot_glass_key"

BOT = {
    "api": None,
    "rodando": False,
    "lucro": 0.0,
    "saldo_atual": 0.0,
    "status_texto": "Aguardando Início",
    "ultima_acao": "Nenhum sinal operado",
    "ativo_atual": "-",
    "estrategia_atual": "MHI",
    "vitorias": 0,
    "derrotas": 0,
    "win_rate": "0%",
    "config": {
        "valor_entrada": 2.0,
        "stop_win": 10.0,
        "stop_loss": 10.0,
        "usar_martingale": "S",
        "niveis_martingale": 1,
        "fator_martingale": 2.2,
        "estrategia_selecionada": "MHI"
    }
}

def bot_loop():
    while True:
        if BOT["rodando"] and BOT["api"]:
            try:
                conf = BOT["config"]
                
                # Verificação de Stops
                if BOT["lucro"] >= float(conf["stop_win"]):
                    BOT["status_texto"] = "META ATINGIDA ✅"
                    BOT["rodando"] = False
                    continue
                if BOT["lucro"] <= -float(conf["stop_loss"]):
                    BOT["status_texto"] = "STOP LOSS ATINGIDO ❌"
                    BOT["rodando"] = False
                    continue

                estrat_nome = conf["estrategia_selecionada"]
                BOT["estrategia_atual"] = estrat_nome
                BOT["status_texto"] = f"Buscando melhor par para {estrat_nome}..."
                
                lista, _ = catag(BOT["api"])
                melhor_par = next((item[1] for item in lista if item[0] == estrat_nome), None)

                if melhor_par and BOT["rodando"]:
                    ativo = melhor_par
                    BOT["ativo_atual"] = ativo

                    # Configurações da lógica original
                    if estrat_nome == "MHI": tf, qnt, idx = 1, 3, 1
                    elif estrat_nome == "Torres Gêmeas": tf, qnt, idx = 1, 4, 2
                    else: tf, qnt, idx = 5, 3, 3 # MHI M5

                    # Momento Sniper (entrada no final do minuto)
                    timestamp = BOT["api"].get_server_timestamp()
                    minutos = float(datetime.fromtimestamp(timestamp).strftime('%M.%S'))
                    
                    entrar = False
                    if idx == 1: entrar = (minutos >= 4.58 and minutos <= 5.00) or (minutos >= 9.58)
                    elif idx == 2: entrar = (minutos >= 3.58 and minutos <= 4.00) or (minutos >= 8.58 and minutos <= 9.00)
                    elif idx == 3: entrar = (minutos >= 29.58 and minutos <= 30.00) or (minutos >= 59.58)

                    if entrar:
                        velas = BOT["api"].get_candles(ativo, tf * 60, qnt, timestamp)
                        if velas and not isinstance(velas, dict):
                            cores = ['Verde' if v['open'] < v['close'] else 'Vermelha' if v['open'] > v['close'] else 'Doji' for v in velas]
                            
                            direcao = None
                            if idx in [1, 3]: # MHI
                                verdes, vermelhas = cores.count('Verde'), cores.count('Vermelha')
                                direcao = 'put' if verdes > vermelhas else 'call' if vermelhas > verdes else None
                            elif idx == 2: # Torres Gêmeas
                                direcao = 'call' if cores[0] == 'Verde' else 'put' if cores[0] == 'Vermelha' else None

                            if direcao and BOT["rodando"]:
                                valor_atual = float(conf["valor_entrada"])
                                
                                # Entrada Sniper + Gale na Próxima Vela
                                for gale in range(int(conf["niveis_martingale"]) + 1):
                                    if not BOT["rodando"]: break
                                    
                                    BOT["status_texto"] = f"Operando {direcao.upper()} em {ativo} (Gale {gale})..."
                                    check, id = BOT["api"].buy_digital_spot_v2(ativo, valor_atual, direcao, tf)

                                    if check:
                                        status, res = False, 0
                                        while not status:
                                            if not BOT["rodando"]: break
                                            status, res = BOT["api"].check_win_digital_v2(id)
                                            time.sleep(0.5)
                                        
                                        BOT["lucro"] += res
                                        BOT["saldo_atual"] = BOT["api"].get_balance()
                                        
                                        if res > 0:
                                            BOT["vitorias"] += 1
                                            BOT["ultima_acao"] = f"WIN em {ativo} (+${res:.2f})"
                                            break # Sucesso, sai do gale
                                        else:
                                            BOT["derrotas"] += 1
                                            if gale < int(conf["niveis_martingale"]):
                                                BOT["ultima_acao"] = f"LOSS. Preparando Gale próxima vela..."
                                                valor_atual *= float(conf["fator_martingale"])
                                            else:
                                                BOT["ultima_acao"] = f"LOSS FINAL em {ativo}"
                                    else:
                                        break
                                
                                total = BOT["vitorias"] + BOT["derrotas"]
                                if total > 0: BOT["win_rate"] = f"{(BOT['vitorias']/total)*100:.1f}%"
                                time.sleep(120) # Pausa pós-trade
                
            except Exception as e:
                BOT["status_texto"] = f"Aguardando mercado..."
        time.sleep(1)

@app.route("/")
def login():
    if "logado" in session: return redirect("/dashboard")
    return render_template("login.html")

@app.route("/", methods=["POST"])
def login_post():
    email, senha, conta = request.form["email"], request.form["senha"], request.form["conta"]
    api = IQ_Option(email, senha)
    check, _ = api.connect()
    if check:
        api.change_balance(conta)
        BOT.update({"api": api, "saldo_atual": api.get_balance()})
        session["logado"] = True
        return redirect("/dashboard")
    return render_template("login.html", erro="Erro de conexão")

@app.route("/dashboard")
def dashboard():
    if "logado" not in session: return redirect("/")
    return render_template("dashboard.html", config=BOT["config"], saldo=BOT["saldo_atual"], lucro=BOT["lucro"])

@app.route("/status")
def status():
    return jsonify({
        "saldo": BOT["saldo_atual"], "lucro": BOT["lucro"], "rodando": BOT["rodando"],
        "status": BOT["status_texto"], "ultima": BOT["ultima_acao"], "winrate": BOT["win_rate"],
        "ativo": BOT["ativo_atual"], "estrategia": BOT["estrategia_atual"]
    })

@app.route("/salvar_config", methods=["POST"])
def salvar_config():
    BOT["config"].update(request.json)
    return jsonify({"status": "ok"})

@app.route("/start")
def start(): BOT["rodando"] = True; return "ok"

@app.route("/stop")
def stop(): BOT["rodando"] = False; return "ok"

@app.route("/logout")
def logout():
    session.clear()
    BOT["rodando"] = False
    return redirect("/")

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)