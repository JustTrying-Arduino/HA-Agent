# Routage modele

## Objectif

Le projet démarre chaque run sur un modèle léger pour réduire les coûts, puis laisse le LLM décider lui-même s'il doit basculer vers le modèle principal pour terminer la tâche.

## Fonctionnement attendu

- Le run démarre avec `cfg.openai_model_light`.
- Si le modèle léger juge la tâche trop complexe, il appelle le tool `escalate_model`.
- À partir de cet instant, tous les appels suivants de la boucle utilisent `cfg.openai_model`.
- Une fois l'escalade effectuée, le tool `escalate_model` n'est plus exposé au modèle.

## Contrat fonctionnel

- Le routage est auto-décidé par le LLM, sans classifieur séparé.
- L'instruction de quand escalader est portée par le prompt runtime.
- Si `openai_model_light == openai_model`, le routage est en pratique désactivé.
- Si un run utilise les deux modèles, les tokens sont comptabilisés séparément.
- Le modèle ayant produit une réponse assistant est enregistré dans `messages.model`.

## Impacts visibles

- Le dashboard peut afficher un badge de modèle sur les messages assistant.
- Les statistiques peuvent ventiler la consommation par modèle.

## Points d'attention

- Toute modification du routeur doit rester alignée entre le tool `escalate_model`, la boucle agent et les instructions du prompt.
- Une évolution de la politique de routage doit documenter à la fois la décision métier et ses impacts coût/observabilité.
