from iqoptionapi.stable_api import IQ_Option
import time
from datetime import datetime

def catag(API, niveis_mg=0):
    pares_abertos = []
    all_asset = API.get_all_open_time()

    for par in all_asset['digital']:
        if all_asset['digital'][par]['open']: pares_abertos.append(par)
    for par in all_asset['turbo']:
        if all_asset['turbo'][par]['open'] and par not in pares_abertos:
            pares_abertos.append(par)

    resultado = []
    
    for par in pares_abertos:
        try:
            velas_m1 = API.get_candles(par, 60, 60, time.time())
            w, l = 0, 0
            direcao_sinal = "CALL" 

            for i in range(len(velas_m1)):
                minutos = int(datetime.fromtimestamp(velas_m1[i]['from']).strftime('%M'))
                
                if (minutos % 5 == 0) and i >= 3:
                    try:
                        v1 = 'Verde' if velas_m1[i-3]['open'] < velas_m1[i-3]['close'] else 'Vermelha'
                        v2 = 'Verde' if velas_m1[i-2]['open'] < velas_m1[i-2]['close'] else 'Vermelha'
                        v3 = 'Verde' if velas_m1[i-1]['open'] < velas_m1[i-1]['close'] else 'Vermelha'
                        
                        direcao = 'PUT' if [v1,v2,v3].count('Verde') > [v1,v2,v3].count('Vermelha') else 'CALL'
                        
                        e1 = 'Verde' if velas_m1[i]['open'] < velas_m1[i]['close'] else 'Vermelha'
                        res_e1 = 'CALL' if e1 == 'Verde' else 'PUT'

                        if res_e1 == direcao: w += 1
                        else: l += 1
                        
                        direcao_sinal = direcao 
                    except: pass
            
            if (w+l) > 0:
                resultado.append({
                    'estrategia': 'MHI',
                    'ativo': par,
                    'direcao': direcao_sinal,
                    'win_rate': round((w/(w+l))*100, 2)
                })
        except: continue

    # Retorna os ativos ordenados do melhor pro pior
    return sorted(resultado, key=lambda x: x['win_rate'], reverse=True)