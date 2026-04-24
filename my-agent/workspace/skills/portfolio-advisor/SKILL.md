# Portfolio Advisor

## Purpose
Lecture factuelle portefeuille Degiro + observations cadrees — utiliser pour etat positions, concentration, drawdown, exposition devise ou allocation.

## Use This Skill When
- L'utilisateur demande un etat du portefeuille ou une analyse de ses positions.
- L'utilisateur demande un avis general sur son allocation, sa concentration, son exposition devise ou ses drawdowns.
- L'utilisateur demande "que penses-tu de mes positions".

## Workflow
1. `degiro_portfolio` pour l'etat des lieux (valeur, cash, P&L, positions, poids, variation vs prix moyen).
2. Identifier objectivement:
   - concentration > 30 % sur une ligne,
   - drawdown > 20 % vs 52w high sur une ligne (via `degiro_quote`),
   - exposition devise dominante (> 70 % d'une meme devise hors cash),
   - cash technique (`FLATEX_EUR`) presente separement.
3. Pour chaque ligne flaggee, completer avec `degiro_quote` et `degiro_indicators` (strategie `swing` ou `rebound` selon le contexte) pour qualifier l'etat technique.
4. Formuler des observations **cadrees par seuils** ("X represente Y % > seuil Z % -> envisager de reduire l'exposition"). Jamais "achete Y", jamais de price target.
5. Conclure avec le rappel obligatoire.

## Observations types (seuils)
- **Concentration**: > 30 % sur une ligne -> envisager de reduire.
- **Drawdown ligne**: < -20 % vs 52w high -> signaler et proposer une analyse technique, pas un achat.
- **Exposition devise**: > 70 % dans une devise non domestique (hors cash) -> signaler le risque de change.
- **Cash**: cash > 20 % sans plan d'emploi -> mentionner mais sans recommander d'achat.
- **Positions sans historique exploitable**: afficher prix actuel, preciser que l'analyse technique n'est pas possible.

## Tools utilises
- `degiro_portfolio` (etat des lieux).
- `degiro_quote` (prix + drawdown 52w).
- `degiro_indicators` (verdict swing ou rebond sur une ligne).
- `web_search` / `web_fetch` pour news fondamentales sur une ligne en drawdown severe.

## Interdictions
- Pas de recommandation d'achat nominative ("achete X").
- Pas de price target ("X vaut 120, objectif 150").
- Pas de conseil en allocation precis en % cible par ligne.
- Aucune mention d'un ordre possible. L'agent **ne peut pas** passer d'ordre sur Degiro (les methodes d'ordre ne sont pas disponibles dans le client vendored).

## Output Style
- Structure: etat des lieux chiffre -> observations cadrees (avec le seuil qui declenche l'observation) -> questions ouvertes pour l'utilisateur -> disclaimer final.
- Disclaimer obligatoire en fin de reponse: "Ces observations ne sont pas un conseil en investissement. L'agent ne peut pas passer d'ordre."
