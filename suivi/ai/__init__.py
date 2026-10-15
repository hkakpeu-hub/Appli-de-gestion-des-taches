"""Couche d'intelligence artificielle (facultative, désactivée par défaut).

Elle est strictement séparée du moteur de tâches : elle ne fait que LIRE les données via
``suivi.ai.context.ContextBuilder`` et interroger un fournisseur (``AIProvider``). Supprimer ce
paquet ne casse aucune autre fonctionnalité.
"""
