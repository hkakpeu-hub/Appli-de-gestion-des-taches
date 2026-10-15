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
| Pièces jointes | `%LOCALAPPDATA%\SuiviTaches\pieces_jointes\` (dossier modifiable dans Paramètres) |

Les données sont volontairement **hors du dossier du code** (et hors OneDrive, qui peut corrompre une base ouverte) :
mettre à jour ou déplacer l'application ne touche jamais aux données.

## Page d'accueil, espaces et modules

Au lancement, une page d'accueil épurée présente vos **espaces** : *Travail*, *Personnel* et *Kingdom* (église).
Chaque espace a ses propres projets, tâches, tableau de bord, planning et historique ; les **alertes** couvrent tous les
espaces (le compteur de l'accueil les additionne, et la notification Windows indique l'espace concerné).
- Cliquez sur une tuile pour entrer dans un espace ; « ‹ Accueil » (en haut de la barre latérale) pour revenir.
- **Paramètres → Espaces et modules** : ajouter un espace (nom, icône, couleur), le renommer, le désactiver (il disparaît
  de l'accueil, ses données restent) ou le supprimer s'il est vide ; activer les modules facultatifs (Budget personnel :
  tuile « bientôt disponible », le module lui-même reste à développer).
- Clic droit sur une tâche → **Déplacer vers l'espace…**.
- À l'import Excel, vous choisissez l'espace de destination de chaque feuille ; la feuille « Actions personnelles » et les
  lignes dont le projet s'appelle « Personnel » vont dans l'espace Personnel.

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
- **Archiver un projet** (page Projets → *Archiver*) : toutes ses tâches disparaissent des listes, recherches, tableau de bord,
  graphiques, planning, alertes et exports. Rien n'est supprimé : cochez « Afficher les projets archivés » puis
  *Désarchiver* pour tout restituer. On ne peut plus créer de tâche dans un projet archivé.
- **Pièces jointes** (fenêtre d'une tâche → onglet *Pièces jointes*) : bouton ou glisser-déposer de photos, Word, Excel,
  PowerPoint, PDF… Les fichiers sont **copiés dans le dossier des pièces jointes** (`<dossier>\<espace>\<n° - tâche>\`),
  la base ne contient que le chemin (elle reste légère). Double-clic = ouvre le fichier ; *Afficher dans l'explorateur* le
  sélectionne dans son dossier. Option « lien » : le fichier reste à son emplacement d'origine. Un 📎 apparaît dans la liste.
  Changer le dossier (Paramètres → Pièces jointes) peut déplacer les fichiers existants. **Attention** : la sauvegarde de
  la base ne contient pas les fichiers joints — incluez ce dossier dans vos propres sauvegardes.
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
import/restauration. Avant une mise à niveau du schéma de la base, une copie `taches_avant_migration_vN.db` est créée à côté de `taches.db`.
Restauration depuis *Importation / exportation* ; l'état précédent est conservé avant.

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
