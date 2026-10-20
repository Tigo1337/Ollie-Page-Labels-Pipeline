# Créer un modèle Silhouette Studio (une fois par mise en page)

*Fichier généré par `python -m engine templates` : modifiez `config/templates/studio_template_setup.md.j2`
et `config/studio_labels.json`, pas ce fichier.*

Chaque taille d'étiquette a **une seule mise en page fixe**, donc **un seul modèle** Studio (`.studio3`),
fait une fois et réutilisé pour toutes les commandes. L'appli fournit, pour chaque mise en page
(page **Templates** de l'appli, ou le dossier `templates/`) :

| Fichier | À quoi il sert |
|---|---|
| `<layout_id>.svg` | le fichier de découpe principal (formes exactes, cercles et rectangles arrondis) |
| `<layout_id>.dxf` | le même, pour Silhouette Studio **Basic** (l'import SVG demande Designer Edition ou plus) |
| `<layout_id>.json` | la position exacte du groupe de découpe (X, Y, L, H en mm), pour vérifier |
| `<layout_id>_calibration.pdf` | les repères + chaque contour de découpe en trait gris fin, sans illustration |

Les deux minuscules **points d'ancrage** (0,01 mm) aux coins de la page (0, 0) et (279,4, 215,9) font que
la sélection complète mesure exactement la page. En la plaçant à X 0 / Y 0, chaque découpe tombe
exactement là où le PDF imprime son étiquette. On supprime ensuite les ancrages.

Toutes les mesures sont en millimètres : réglez Studio en **mm**.

## Étapes (une fois par mise en page)

1. **DXF seulement** (Studio Basic) : **Édition** (Edit) → **Préférences…** (Preferences…) ⚠ → onglet **Importer** (Import) ⚠ :
   **Ouverture DXF** (DXF Open) ⚠ = **Tel quel** (As-is) ⚠, puis OK. Ainsi le DXF garde ses dimensions exactes.
2. **Fichier** (File) → **Nouveau** (New).
3. Panneau **Paramètres de page** (Page Setup) : **Taille du support** (Media Size) ⚠ **Lettre** (Letter), **Orientation** **Paysage** (Landscape)
   (comme les modèles SCM), **Tapis de coupe** (Cutting Mat) ⚠ 12 × 12 po.
4. **Fichier** (File) → **Fusionner…** (Merge…) le fichier `<layout_id>.svg` (ou le `.dxf`) : il arrive dans ce
   document déjà réglé. (**Ouvrir…** (Open…) marche aussi, mais ouvre un nouvel onglet : refaites alors l'étape 3 dans cet onglet.)
5. **Tout sélectionner** (Select All) (Ctrl+A), puis **Grouper** (Group) (Ctrl+G).
6. Panneau **Transformer** (Transform) → **Déplacer** (Move) ⚠ : choisissez le **point de référence** (reference point) ⚠ **en haut à gauche**, puis
   **Position** **X 0**, **Y 0**. Vérifiez que **L** (W) × **H** = **279,4 × 215,9** mm
   (sinon l'import n'est pas à l'échelle : arrêtez et vérifiez les unités).
7. **Dissocier** (Ungroup) ⚠ (Ctrl+Maj+G). Zoomez sur le coin en haut à gauche de la page, tracez un petit cadre de
   sélection autour du point d'ancrage et appuyez sur **Suppr** (Delete). Même chose pour le coin en bas à droite.
8. **Tout sélectionner** (Select All) : les valeurs X / Y / **L** (W) / **H** doivent être celles du tableau
   plus bas (et du `<layout_id>.json`) à 0,01 mm près. **Ne déplacez plus rien.**
9. Panneau **Impression et découpe** (Print & Cut) ⚠ → **Repères d'impression** (Registration Marks) : activés, **Type 1**, **Longueur** (Length) **10 mm**,
   **Épaisseur** (Thickness) **1 mm**, **Retrait** (Inset) **10 mm**.
   Les repères affichés doivent tomber dans les coins hachurés de l'aperçu (carré en haut à gauche en paysage).
10. **Fichier** (File) → **Enregistrer sous…** (Save As…) (**Enregistrer sur le disque dur** (Save to Hard Drive) ⚠) : `<layout_id>.studio3`.
11. Imprimez `<layout_id>_calibration.pdf` sur du papier ordinaire, à 100 % (**Taille réelle** (Actual size) ⚠ dans
    la fenêtre d'impression du lecteur PDF, sans « ajuster à la page »). Placez la feuille sur le tapis comme
    une planche normale, ouvrez le modèle et faites une découpe légère. **Chaque découpe doit tomber sur son
    trait gris.**
    * Décalage régulier dans une direction : lancez le **Calibrage** (Calibration) de Studio, puis vérifiez à
      nouveau le **Retrait** (Inset) (10 mm) des repères.
    * Une seule ligne de labels décalée, ou une découpe à la mauvaise place : le modèle a bougé, refaites-le
      depuis l'étape 2.
12. Dans l'appli, page **Templates** : téléversez `<layout_id>.studio3` dans l'emplacement de la mise en page.
    L'appli enregistre l'empreinte de la géométrie : si la géométrie change un jour, le fichier est marqué
    **périmé** en rouge et n'est plus mis dans les lots.

## Mises en page actuelles

| Mise en page | Découpes | X | Y | L | H |
|---|---:|---:|---:|---:|---:|
| `chels-pencil-v1` | 60 | 14.10 | 13.20 | 251.20 | 189.50 |
| `chels-small-v1` | 62 | 12.80 | 15.20 | 253.80 | 185.50 |
| `chels-medium-v1` | 30 | 23.60 | 10.20 | 232.20 | 195.50 |
| `chels-large-v1` | 22 | 17.80 | 10.20 | 243.80 | 195.50 |
| `chels-tag-v1` | 110 | 12.80 | 11.55 | 253.80 | 192.80 |
| `chels-round-v1` | 40 | 10.00 | 10.00 | 259.40 | 182.20 |
| `chels-shoe-v1` | 32 | 12.85 | 11.70 | 253.70 | 192.50 |

(mm, repère de Studio en paysage, ancrages exclus)

## Raccourci optionnel : `dxf_to_studio3.py` de SCM

[silhouette-card-maker](https://github.com/Alan-Cha/silhouette-card-maker) (licence MIT) contient
[`dxf_to_studio3.py`](https://github.com/Alan-Cha/silhouette-card-maker/blob/main/dxf_to_studio3.py), qui
automatise ces étapes dans Studio (Windows seulement, pilotage de l'interface ; calibrage unique décrit dans
leur [guide](https://github.com/Alan-Cha/silhouette-card-maker/blob/main/hugo/content/miscellaneous/template.md)) :

```
python dxf_to_studio3.py single <layout_id>.dxf <layout_id>.studio3 --paper_size letter --orientation landscape --registration --unit mm --reg_length 10 --reg_thickness 1 --reg_inset 10 --no_center
```

* `--no_center` est obligatoire : nos grilles ne sont pas centrées sur la page.
* **Attention :** le script retourne toujours la sélection verticalement après l'import (pour corriger le
  remplissage d'image de leurs cartes). Avec nos ancrages, cela fait un miroir de la mise en page autour du
  centre de la page : sans effet pour les grilles symétriques, mais **faux pour `chels-round`** (rangées
  décalées). Après le script, faites toujours les vérifications des étapes 8 et 11 ; pour le rond, un Y de
  23,70 au lieu de 10,00 signale le miroir.

## Libellés à confirmer

Les libellés marqués ⚠ ci-dessus sont des traductions probables, pas vérifiées dans votre Studio. Corrigez-les
dans `config/studio_labels.json` puis relancez `python -m engine templates`.

| Clé | Français | English |
|---|---|---|
| `save_to_disk` | Enregistrer sur le disque dur | Save to Hard Drive |
| `preferences` | Préférences… | Preferences… |
| `import_tab` | Importer | Import |
| `dxf_open` | Ouverture DXF | DXF Open |
| `as_is` | Tel quel | As-is |
| `cutting_mat` | Tapis de coupe | Cutting Mat |
| `media_size` | Taille du support | Media Size |
| `ungroup` | Dissocier | Ungroup |
| `move` | Déplacer | Move |
| `ref_point` | point de référence | reference point |
| `print_cut` | Impression et découpe | Print & Cut |
| `pdf_actual_size` | Taille réelle | Actual size |

