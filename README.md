# QGIS Sentinel 2 script overview
This script is used within [QGIS](https://github.com/qgis/QGIS) to facilitate the automatic download of large datasets of Sentinel-2 imagery.
The script uses the [Sentinelhub-py](https://github.com/sentinel-hub/sentinelhub-py) package to authenticate, retrieve the catalog and finally download the available tiles within the requested area from Sentinel Hub.

---

## Using the script in QGIS

1.Installing Sentinelhub package
The sentinelhub python package is required to be installed into the QGIS environment for the script to work.
Install this package by going into the QGIS python console and first importing pip.
`import pip`
Then install sentinelhub
`pip.main(['install', 'sentinelhub'])`

2.Configuring the script
Lines **188 + 189** require adjusting to allow the script to work.
`config.sh_client_id = "{your id}"
config.sh_client_secret = "{your client secret}"`

These must be filled in with credentials obtained from the sentinelhub OAuth client.

---

Further guidance can be found [here](https://bmharry.com/sentinelqgis).
