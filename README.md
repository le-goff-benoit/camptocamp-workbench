# Camptocamp Workbench

Dashboard local pour les demandes clients, emails, agenda et releases, avec Codex
et/ou Claude Code. Le workflow intégré fonctionne sans profils d’agents ni dépôt
privé. Chaque collègue installe son instance et connecte ses propres comptes.

**[Guide pratique PDF](docs/guide-camptocamp-workbench.pdf)** ·
[Présentation PDF actualisée](docs/presentation-camptocamp-workbench.pdf) ·
[Source du guide](docs/guide.md) · [Dépendances Python](requirements.txt)

## Fonctions

- Accueil « À traiter » : plans à décider, travaux à vérifier et blocages.
- Les 50 derniers emails de la boîte de réception et, séparément, les 50
  derniers échanges de chaque projet. Les transferts internes sont rapprochés
  du projet à partir des en-têtes du client d’origine, sans tag obligatoire.
- À l’ouverture d’un email : **Résumé de la demande du client** et **Ma
  proposition / analyse / solution**, à partir du message complet. Le résultat
  est enregistré. Seul **Réanalyser** le renouvelle, même après actualisation,
  changement de fournisseur, échec ou redémarrage du service.
- Relève des emails et du calendrier toutes les 5 minutes, si activée et si le
  service fonctionne. Cette relève ne lance aucune analyse d’email.
- Email vers tâche : projet, release et titre explicites, texte complet,
  protection contre les doublons et ouverture du travail créé.
- Releases et demandes : plan à approuver, réalisation, preuves, réception et
  clôture. Bibliothèque PDF/Word en lecture seule et repères d’environnements.
- Terminaux Codex, Claude ou shell dans le dépôt du projet.

Les sources Google sont des relevés de lecture. Leur actualisation ne crée pas
de tâches, n’envoie pas d’emails et ne modifie pas le calendrier.

## Installation pour un collègue

La cible est **Linux avec un bureau**, notamment Ubuntu 22.04/24.04. Le lanceur
et le service utilisent `xdg-open` et `systemd --user`. Windows natif et macOS
ne sont pas pris en charge par cet installateur. Ni Docker ni serveur Odoo
ne sont nécessaires pour utiliser Workbench.

### 1. Prérequis système

Sur Ubuntu/Debian :

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-pip \
  sqlite3 poppler-utils xdg-utils ca-certificates
```

Installer **Node.js 24 LTS à jour**, avec npm, depuis
[Node.js](https://nodejs.org/en/download) ou un gestionnaire de versions utilisateur.
Le paquet OpenClaw de référence requiert Node >= 22.19.0.

```bash
node --version
npm --version
python3 --version
```

Le backend utilise **Python >= 3.10 et sa bibliothèque standard**, dont SQLite
avec FTS5. Aucun paquet Python n’est nécessaire pour le faire fonctionner.
`requirements.txt` documente ce choix. `requirements-docs.txt` sert uniquement
à reconstruire le PDF. `poppler-utils` fournit `pdftotext` pour la bibliothèque.

### 2. OpenClaw et fournisseurs

Cette édition utilise les versions de référence ci-dessous. Les connexions
natives dépendent des protocoles des CLIs : vérifier les tests avant de changer
ces versions.

```bash
npm install --global openclaw@2026.5.18
```

Installer au moins un fournisseur pour les analyses et les sources Google :

```bash
# Codex
npm install --global @openai/codex@0.167.0
codex login

# Claude Code, seul ou en complément
npm install --global @anthropic-ai/claude-code@2.1.322
claude auth login
```

Utiliser son propre compte et les accès autorisés par son organisation. Le
workflow manuel reste disponible sans fournisseur connecté. Une clé API ne
remplace pas une connexion aux plugins Gmail/Google Calendar.

Références officielles : [OpenClaw](https://docs.openclaw.ai/install),
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli),
[Claude Code](https://code.claude.com/docs/en/setup).

### 3. Installer le dashboard

```bash
git clone https://github.com/le-goff-benoit/camptocamp-workbench.git
cd camptocamp-workbench
bash install.sh --check
bash install.sh --install
python3 scripts/manage.py open
```

`--check` ne modifie aucune configuration. `--install` crée un profil OpenClaw
**workbench**, un service utilisateur et le lanceur **Camptocamp Workbench**.
Le profil OpenClaw par défaut reste distinct. Après un déplacement du dossier
cloné, réinstaller le lanceur et le service.

Adresse : `http://127.0.0.1:18793/workbench/`. Le lanceur initialise la session
du navigateur. Les ports **18793** (Gateway) et **18794** (backend) doivent être
libres avant le démarrage.

## Première configuration

1. Dans **Paramètres**, indiquer le dossier contenant ses dépôts Git et la
   profondeur de découverte. Aucun projet ni accès client n’est préconfiguré.
2. Choisir séparément **Emails et agenda** et **Analyses et propositions de plan**.
   Sur une installation Claude seule, sélectionner Claude Code pour les deux.
3. Dans **Connexions**, connecter ses propres sources Google. Pour Codex : ouvrir
   `codex`, puis `/plugins`, installer et connecter Gmail et Google Calendar.
   Pour Claude : les connecter dans [les connecteurs Claude](https://claude.ai/customize/connectors),
   avec le même compte Claude que le terminal, puis cliquer sur **Vérifier les
   connexions Claude** dans Workbench.
4. Cliquer sur **Actualiser les emails et l’agenda**. Un relevé réussi confirme
   l’accès effectif. « Installé » confirme seulement la présence du logiciel.
5. Activer **Actualiser automatiquement toutes les 5 minutes**, puis enregistrer.
   Ce choix est désactivé par défaut sur un nouveau poste.
6. Dans **Réglages du projet**, renseigner les adresses ou domaines du client.
   Une recherche Gmail explicite peut remplacer le critère automatique.
7. Dans **Bibliothèque**, ajouter les dossiers documentaires utiles. Les accès
   et environnements ne sont pas partagés automatiquement entre collègues.

### Vérifier le premier démarrage

- Le projet apparaît et son terminal s’ouvre dans le bon dépôt.
- Le relevé général contient au plus 50 emails et le projet sa propre liste.
- Un email s’ouvre avec ses deux blocs. Fermer puis rouvrir : la date d’analyse
  reste identique. Le message original se déplie en dessous.
- Une release intégrée peut être ouverte et recevoir une demande manuelle.
- Une actualisation affiche sa date de réussite ou son erreur et conserve le
  dernier relevé réussi.

## Releases sans agents préinstallés

Le workflow intégré est fourni ici : nouvelle demande, analyse, plan à approuver,
réalisation, vérification, réception, puis clôture de release. Le consultant
utilise les boutons. Aucun profil personnalisé de l’auteur n’est nécessaire.

Pour suivre un email, l’ouvrir, choisir **Projet de destination**, **Release
ouverte** et **Titre de la tâche**, puis **Créer une tâche depuis cet email**.
Le message complet est récupéré et la tâche s’ouvre. Une proposition d’analyse
ne constitue pas une approbation du plan ni une autorisation de livraison.

Le suivi intégré est créé dans `memory/releases/` du dépôt client : demandes,
plan, décisions, recette et preuves. Le dashboard écrit les états et décisions.
Le consultant n’a pas à recopier les mêmes informations à la main. Git sert à
partager le travail.

### Compatibilité historique facultative

Les anciennes releases `changelog/` et `release/` gardent leur moteur d’origine.
Leurs marqueurs et tableaux de points restent consultables. L’adaptateur avancé,
dans Paramètres, peut utiliser un moteur installé contenant `odoo-release.sh`,
`odoo_plan.py` et `odoo_mail.py`, avec ses modèles. Il est facultatif pour une
nouvelle release intégrée. Une release historique ouverte doit être poursuivie
avec son moteur avant d’ouvrir un second workflow dans le même projet.

Le lecteur externe des anciennes mesures est aussi facultatif. Sans lui, les
mesures restent inconnues et les points visibles. Un total inconnu ne devient
pas zéro. Les sources Odoo, packs métier et bases clients ne sont pas distribués.

## Service, mises à jour et sauvegardes

```bash
python3 scripts/manage.py status
python3 scripts/manage.py open
python3 scripts/manage.py stop
python3 scripts/manage.py start
python3 scripts/manage.py start --restart
journalctl --user -u openclaw-workbench.service -n 80 --no-pager
```

Fermer les terminaux et attendre la fin des analyses avant un redémarrage. Les
terminaux ne survivent pas à l’arrêt du service. Les analyses email enregistrées
survivent. Une analyse interrompue attend un clic sur **Réanalyser**.

Mise à jour : arrêter les travaux, `git pull --ff-only`, vérifier les dépendances
avec `bash install.sh --check`, puis `python3 scripts/manage.py start --restart`.

| Élément | Emplacement |
| --- | --- |
| Profil Gateway | `~/.openclaw-workbench/` |
| Réglages, sources et analyses | `~/.local/share/openclaw-workbench/` |
| Demandes et releases | Dans chaque dépôt de projet |
| Service | `~/.config/systemd/user/openclaw-workbench.service` |
| Lanceur | `~/.local/share/applications/openclaw-workbench.desktop` |

Sauvegarder les dépôts et l’état local dans un emplacement privé. Les sessions
et identifiants sont propres à chacun. Aucun état local, email ou jeton n’est
à ajouter au dépôt public. Le backend écoute uniquement sur la boucle locale.

## Dépannage

| Symptôme | Action |
| --- | --- |
| « Authentification requise » du Control UI | Ouvrir le lanceur ou `python3 scripts/manage.py open`. Utiliser `/workbench/`. Le Control UI est une autre vue. |
| Google en 401 ou « à reconnecter » | Reconnecter le compte chez le fournisseur choisi, vérifier le compte du terminal, puis actualiser. |
| CLI présente dans le terminal, absente du service | Vérifier son installation utilisateur et son PATH, puis réinstaller Workbench. |
| Emails d’un projet incomplets | Vérifier adresses/domaines et recherche Gmail, puis actualiser le projet. |
| Analyse email en échec | Corriger la connexion ou le fournisseur, puis cliquer sur **Réanalyser**. |
| Vue historique sans mesures | Compatibilité facultative absente. Le suivi intégré reste opérationnel. |
| Port déjà occupé | Arrêter l’autre instance Workbench avant de démarrer. |
| Bibliothèque PDF vide | Vérifier `pdftotext` et la présence de texte. Un scan demande un OCR préalable. |

## Tests et développement

Les tests utilisent des CLIs fictives : aucun compte Google ni abonnement n’est
utilisé. Trois intégrations historiques facultatives sont ignorées si leurs
outils ne sont pas installés.

```bash
npm ci
npm run test:portable
npx playwright install --with-deps chromium
npm run test:ui
```

`test:portable` vérifie le backend sans outils, sources ou lecteur historique
personnels. La recette navigateur utilise ses propres adaptateurs fictifs.
Pour l’installation active, `python3 scripts/live_check.py` est un contrôle de
lecture seule. Node et Playwright servent aux tests, pas au backend Python.

Le modèle de recette GitHub Actions est fourni dans [ci/github-actions.yml](ci/github-actions.yml).
Il peut être copié dans `.github/workflows/` avec un compte autorisé à gérer les
workflows GitHub. Son activation est facultative pour installer et utiliser Workbench.

### Reconstruire le guide PDF

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r requirements-docs.txt
.venv-docs/bin/python scripts/build_guide.py
```

Le guide est issu de la présentation « Camptocamp - Workbench et agents Odoo »,
complétée avec les fonctions livrées. Sa source est `docs/guide.md`. Les captures
distribuées utilisent exclusivement des projets et emails fictifs. Les licences
des composants embarqués figurent dans [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
