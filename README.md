# simpleMailing

Application web minimaliste pour gérer l'envoi d'emails en s'appuyant sur l'API de Listmonk.

## Fonctionnalités

- Connexion à une instance Listmonk via URL + identifiants API
- Récupération des listes (`/api/lists`)
- Création et tentative de démarrage d'une campagne d'email à partir des listes sélectionnées

## Lancer l'application

```bash
python app.py --host 0.0.0.0 --port 8080
```

Puis ouvrir : `http://localhost:8080`

## Tests

```bash
python -m unittest discover -s tests
```
