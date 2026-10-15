# Suivi des tâches

Application Windows (Python / PySide6 / SQLite) de gestion de tâches, projets, échéances et planning.
Fonctionne 100 % hors ligne. Tous les textes sont en français.

## Installation et lancement

1. Double-cliquez sur **`install.bat`** (une seule fois, Internet requis). Il crée un environnement Python
   dans `%LOCALAPPDATA%\SuiviTaches\venv`, installe les dépendances et propose un raccourci Bureau.
   Prérequis : Python 3.10+ (python.org, cocher « Add python.exe to PATH »).
2. Double-cliquez sur **`start.bat`** (ou le raccourci) pour ouvrir l'application.
3. **Importer votre historique** : *Importation / exportation* → « Choisir un fichier à importer… » →
   sélectionnez `Matrice des compétences suivi des actions.xlsx` → vérifiez la prévisualisation → *Importer*.

Exécutable `.exe` (facultatif) : lancez **`build_exe.bat`** → `dist\SuiviTaches\SuiviTaches.exe`
(copier tout le dossier `dist\SuiviTaches`).

## Où sont mes données ?

| Élément | Emplacement |
|---|---|
| Base de données | `%LOCALAPPDATA%\SuiviTaches\taches.db` |
| Sauvegardes | `%LOCALAPPDATA%\SuiviTaches\sauvegardes\` |
| Journaux techniques | `%LOCALAPPDATA%\SuiviTaches\journaux\` |

Les données sont volontairement **hors du dossier du code** (et hors OneDrive, qui peut corrompre une base ouverte) :
mettre à jour ou déplacer l'application ne touche jamais aux données.

## Utilisation courante

- **Ajout rapide** (barre du haut) : `Relancer Donald #Centaures !demain @Hermann` puis Entrée.
  `#projet` · `@responsable` · `!aujourd'hui | !demain | !+3j | !25/12`. `Ctrl+N` : fenêtre complète.
- **Clic droit** sur une tâche : terminer, changer statut/priorité, supprimer. Double-clic : modifier
  (onglets Détails, Commentaires datés, Historique).
- **Tableau de bord** : les cartes et graphiques sont cliquables ; mise à jour immédiate après toute modification.
- **Vues prédéfinies** (Toutes les tâches) : jour, semaine, retards, échéances, bloquées, sans deadline,
  récentes, terminées… combinables avec recherche (accents/casse ignorés, y compris commentaires), projet,
  statut, responsable, priorité, période, niveau de retard. Tri en cliquant sur les en-têtes.
- **Planning** : semaine ou jour ; glisser un bloc pour le déplacer, tirer son bord bas pour changer la durée,
  double-clic sur un créneau vide pour créer. Chevauchements encadrés en rouge, créneaux libres en vert,
  tâches sans horaire listées à droite.
- **Alertes** : centre de notifications (compteur dans le menu), marquer lu, reporter (1 h, 3 h, demain, 3 j),
  ouvrir la tâche. Notifications natives Windows ; en fermant la fenêtre, l'application reste dans la zone de
  notification pour continuer à alerter (*Quitter* via clic droit sur l'icône).
- **Suppression** : corbeille (Historique → Corbeille) avec restauration ; suppression définitive sur confirmation.

## Règles métier clés

- Une tâche **Terminée** ou **Annulée** n'est jamais en retard. Une deadline « aujourd'hui » n'est pas un retard.
- Les règles reposent sur la *nature* du statut, pas sur son libellé : vous pouvez renommer/ajouter des statuts.
- Alertes : une alerte n'est notifiée qu'une fois (état mémorisé en base, même après redémarrage). Retards,
  « non démarrée » et blocages prolongés sont réémis tous les N jours (Paramètres). Changer la deadline
  réinitialise les alertes de la tâche.
- Doublons à l'import : même intitulé + même date de début + même projet.

## Import / export Excel

- Les feuilles sont reconnues par leurs en-têtes ; seules celles avec « Action » + statut/deadline/responsable
  sont proposées (les feuilles « Compétences », « WINNING », « Rapport » sont ignorées).
- Avant import : sauvegarde automatique ; l'import est atomique (tout ou rien) ; bilan final.
- Choix d'interprétation appliqués au fichier d'origine (modifiables à l'aperçu ou après import) :
  `1-Terminé / 2-En cours / 3-Non dem` → Terminée / En cours / À faire ; colonne I sans titre → « date complémentaire » ;
  dans « Actions personnelles », les dates placées sous « Heure de début » deviennent des deadlines et le projet
  par défaut est « Personnel » ; « SuiviMigration » reçoit le projet « SuiviMigration » (champ modifiable à l'aperçu).
- Export : feuille « actions journalières » (même structure que votre fichier) + feuille « Toutes les données » ;
  export de toutes les tâches ou de la vue filtrée.

## Sauvegarde et restauration

Automatique (réglable : intervalle, nombre conservé) au démarrage et pendant l'utilisation, plus avant chaque
import/restauration. Restauration depuis *Importation / exportation* ; l'état précédent est conservé avant.

## Assistant IA (facultatif, désactivé par défaut)

Paramètres → Assistant IA : activer, indiquer le modèle, coller la clé API Anthropic. La clé est stockée dans le
**coffre d'identifiants Windows** (jamais en base, journal ou code). Sans clé, tout le reste fonctionne ; les
« analyses rapides » de la page Assistant IA sont calculées localement. Le code IA (`suivi/ai`) ne fait que lire
les données (résumé JSON) : il peut être remplacé ou supprimé sans toucher au moteur de tâches.

## Mise à jour de l'application

1. Fermez l'application (clic droit sur l'icône de notification → Quitter).
2. Remplacez le contenu du dossier du projet par la nouvelle version (ne supprimez rien dans `%LOCALAPPDATA%\SuiviTaches`).
3. Relancez `install.bat` (met à jour les dépendances) puis `start.bat`. Le schéma de la base est migré
   automatiquement et une sauvegarde est faite au démarrage.

## Architecture

```
suivi/
  core/    logique métier sans interface : tasks, projects, statuses, rules, alerts, planning, metrics, presets, backup, settings
  db/      SQLite (migrations versionnées, transactions, sauvegarde/restauration)
  excel/   importer.py (aperçu, doublons, import atomique), exporter.py
  ai/      couche IA facultative (contexte, fournisseur Claude, coffre de clé, analyses locales)
  ui/      interface PySide6 (pages, graphiques QPainter, dialogues, fenêtre principale, zone de notification)
  context.py  assemblage des services ; app.py point d'entrée
tests/     tests automatisés (pytest)
```

Tests : `"%LOCALAPPDATA%\SuiviTaches\venv\Scripts\python.exe" -m pytest` (pytest requis : `pip install -r requirements-dev.txt`).
