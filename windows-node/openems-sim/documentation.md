# Documentation — Simulateur EMS Énergie Verte (Solaire + Hydrogène) pour OpenClaw

Ce simulateur sert à **générer des logs réalistes** et à **injecter des anomalies** afin de tester la détection automatique d'anomalies par OpenClaw (via votre PC comme node).

## 1) Contexte simulé
- Production photovoltaïque (PV)
- Batterie (SoC, charge/décharge)
- Électrolyseur (consommation kW, production H2)
- Réservoir H2 (pression)
- Bus DC + température onduleur

Le cycle jour/nuit est accéléré (~4 minutes) pour une démo vivante.

## 2) Formats de logs
### A) JSONL (recommandé)
Fichier: `ems_telemetry.jsonl`
- 1 JSON par ligne
- Champs clés:
  - `status`: `OK` ou `ALARM`
  - `anomalies`: booléens (`hv_dc_bus`, `lv_dc_bus`, `h2_leak`, etc.)

OpenClaw doit **tail** ce fichier et déclencher une alerte si:
- `status == "ALARM"` OU
- `any(anomalies.* == true)`

### B) Log texte OpenEMS-like (optionnel)
Fichier: `openems_simulation.log`
- Lisible pour un humain
- Contient des lignes `INFO` et `ERROR`

## 3) Injection d'anomalies
Boutons UI (clic = ALARM / re-clic = NORMAL):
- Haute tension DC bus (HV)
- Basse tension (LV)
- Fuite Hydrogène (baisse rapide pression)
- Surchauffe onduleur
- Surpression électrolyseur
- Perte communications

## 4) Exécution
### Simulateur UI
```powershell
python openems_simulator.py
```

### Listener exemple
JSONL:
```powershell
python open_claw_listener.py --file "C:\Users\xfive\Desktop\ems_sim\ems_telemetry.jsonl"
```

Texte:
```powershell
python open_claw_listener.py --file "C:\Users\xfive\Desktop\ems_sim\openems_simulation.log"
```

## 5) Intégration OpenClaw (MVP)
- Un cron/skill qui lit la dernière ligne JSONL, ou qui tail en continu.
- Si `ALARM`, envoyer une notification Telegram + conserver un compteur d'anomalies.
