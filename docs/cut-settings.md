# Réglages de découpe (Silhouette Cameo 5)

*Fichier généré par `python -m engine docs` : modifiez `config/templates/cut_settings.md.j2` et
`config/studio_labels.json`, pas ce fichier.*

Ce sont des **points de départ**, pas des valeurs garanties. Le but est une **découpe à mi-chair**
(kiss cut) : la lame traverse le laminé et le vinyle, **pas** la pellicule de support.

## Réglages de départ

| Réglage | Valeur de départ |
|---|---|
| Lame | **AutoLame** (AutoBlade) |
| **Profondeur** (Depth) | 2 |
| **Force** | 12 |
| **Vitesse** (Speed) | 4 |
| **Passages** (Passes) | 1 |

## Un matériau personnalisé par finition

Chaque finition commence par un **Test de découpe** (Test Cut), puis ses réglages sont enregistrés comme un
**Matériau** (Material) ⚠ personnalisé (**Ajouter un matériau** (Add Material) ⚠), pour ne plus avoir à les chercher :

| Finition | Nom du matériau |
|---|---|
| Matte | `Chels – vinyle + lam. mat` |
| Glossy | `Chels – vinyle + lam. brillant` |
| Holographic | `Chels – vinyle + lam. holo` |

1. Panneau **Envoyer** (Send) : choisissez le matériau de la finition.
2. Faites un **Test de découpe** (Test Cut) dans un coin libre (hors des zones des repères).
3. Le petit carré doit se décoller proprement **sans** marquer le support. Trop léger : montez la
   **Force** ; le support est coupé : baissez la **Force** ou la **Profondeur** (Depth).
4. Enregistrez les réglages dans le matériau.

## Notes

* Le laminé **holographique** demande en général plus de **Force** : montez de 2 à la fois.
* Utilisez une lame neuve de bonne qualité.
* Le tapis doit bien coller ; s'il est fatigué, scotchez les bords de la feuille.
* Si le bord gauche est mal coupé, vérifiez d'abord l'adhérence du tapis et la position des
  rouleaux presseurs, **avant** de monter la **Force**.
* Un décalage de toutes les découpes dans une même direction n'est pas un réglage de lame : voir
  le **Calibrage** (Calibration) dans `docs/studio-template-setup.md`.

## Option : couper la feuille en trois tiers à la machine (désactivée par défaut)

`templates/trim_line.svg` (et `.dxf`) contient une ligne de coupe traversante sur chacune des
2 lignes de coupe des tiers (X 93.133 et 186.267 mm
en paysage), en **bleu** sur le calque `TRIM`.
Pour l'utiliser : **Fichier** (File) → **Fusionner…** (Merge…) ce fichier dans le modèle, placez-le à X 0 / Y 0
(les points d'ancrage), supprimez les ancrages, puis dans **Envoyer** (Send) choisissez
**Découper par couleur de ligne** (Cut by Line Color) et donnez au bleu des réglages de coupe complète (plus de
**Profondeur** (Depth) et de **Force**, 2 **Passages** (Passes)).

**Attention :** une coupe traversante marque le tapis à chaque feuille. Sans elle, coupez aux
ciseaux ou au massicot aux repères de coupe imprimés.
