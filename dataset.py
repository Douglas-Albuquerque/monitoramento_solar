import numpy as np
import pandas as pd

np.random.seed(42)

n = 10000

numero_tickets = np.random.randint(50, 401, n)

tickets_criticos = np.array(
    [np.random.randint(0, int(0.2 * t) + 1) for t in numero_tickets]
)

severidade_media = np.round(np.random.uniform(1.0, 5.0, n), 2)

numero_analistas_turno = np.random.randint(2, 13, n)

ruido = np.random.normal(0, 3, n)

horas_totais_turno = (
    0.15 * numero_tickets
    + 0.8 * tickets_criticos
    + 1.5 * severidade_media
    - 0.7 * numero_analistas_turno
    + ruido
)

horas_totais_turno = np.round(horas_totais_turno, 2)

df = pd.DataFrame(
    {
        "numero_tickets": numero_tickets,
        "tickets_criticos": tickets_criticos,
        "severidade_media": severidade_media,
        "numero_analistas_turno": numero_analistas_turno,
        "horas_totais_turno": horas_totais_turno,
    }
)

df.to_csv("dataset_soc_regressao_linear.csv", index=False)

df.head()
