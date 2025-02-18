from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterBoolean,
    QgsVectorLayer,
    QgsProject,
)
import os
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta
from sentinelhub import (
    SHConfig,
    DataCollection,
    SentinelHubCatalog,
    SentinelHubRequest,
    BBox,
    bbox_to_dimensions,
    CRS,
    MimeType,
)
from osgeo import gdal

class SentinelHubDownloadAlgorithm(QgsProcessingAlgorithm):

    INPUT_LAYER = 'INPUT_LAYER'
    START_DATE = 'START_DATE'
    END_DATE = 'END_DATE'
    DOWNLOAD_MODE = 'DOWNLOAD_MODE'
    OUTPUT_DIR = 'OUTPUT_DIR'
    STEP_SIZE = 'STEP_SIZE'
    CALC_NDVI = 'CALC_NDVI'
    CALC_NDSI = 'CALC_NDSI'
    CALC_NDWI = 'CALC_NDWI'
    
    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return SentinelHubDownloadAlgorithm()

    def name(self):
        return 'sentinelmaster'

    def displayName(self):
        return 'Sentinel Download noDB'

    def group(self):
        return 'Sentinel Scripts'

    def groupId(self):
        return 'sentinelscripts'

    def shortHelpString(self):
        return self.tr("Downloads Sentinel-2 data based on the extent of the input layer, and specified date range, with optional processing for NDVI, NDSI, or NDWI.")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LAYER,
                self.tr('Input Layer'),
                [QgsProcessing.TypeVectorAnyGeometry]
            )
        )
    
        self.addParameter(
            QgsProcessingParameterString(
                self.START_DATE,
                self.tr('Start Date (YYYY-MM-DD)'),
                defaultValue=datetime.now().strftime("%Y-%m-%d")
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.END_DATE,
                self.tr('End Date (YYYY-MM-DD)'),
                defaultValue=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.DOWNLOAD_MODE,
                self.tr('Download Mode'),
                options=['All', 'Monthly'],
                defaultValue=0
            )
        )

        self.addParameter(
            QgsProcessingParameterString(
                self.STEP_SIZE,
                self.tr('Step Size for Bounding Box (degrees), 0.22 max'),
                defaultValue="0.22"
            )
        )

        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Output Directory')
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CALC_NDVI,
                self.tr('Calculate NDVI'),
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CALC_NDSI,
                self.tr('Calculate NDSI'),
                defaultValue=False
            )
        )

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CALC_NDWI,
                self.tr('Calculate NDWI'),
                defaultValue=False
            )
        )
        
    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        start_date = self.parameterAsString(parameters, self.START_DATE, context)
        end_date = self.parameterAsString(parameters, self.END_DATE, context)
        download_mode = self.parameterAsEnum(parameters, self.DOWNLOAD_MODE, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        step_size = float(self.parameterAsString(parameters, self.STEP_SIZE, context))

        calc_ndvi = self.parameterAsBoolean(parameters, self.CALC_NDVI, context)
        calc_ndsi = self.parameterAsBoolean(parameters, self.CALC_NDSI, context)
        calc_ndwi = self.parameterAsBoolean(parameters, self.CALC_NDWI, context)

        if input_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT_LAYER))

        min_x, min_y, max_x, max_y = None, None, None, None

        for feature in input_layer.getFeatures():
            geom = feature.geometry()
            if geom is not None:
                bbox = geom.boundingBox()
                if min_x is None or bbox.xMinimum() < min_x:
                    min_x = bbox.xMinimum()
                if min_y is None or bbox.yMinimum() < min_y:
                    min_y = bbox.yMinimum()
                if max_x is None or bbox.xMaximum() > max_x:
                    max_x = bbox.xMaximum()
                if max_y is None or bbox.yMaximum() > max_y:
                    max_y = bbox.yMaximum()

        if min_x is None or min_y is None or max_x is None or max_y is None:
            raise QgsProcessingException("Unable to determine the bounding box of the input layer.")

        def generate_bounding_boxes(min_x, min_y, max_x, max_y, step):
            current_x = min_x
            current_y = min_y

            while current_x < max_x:
                while current_y < max_y:
                    yield (current_x, current_y, min(current_x + step, max_x), min(current_y + step, max_y))
                    current_y += step
                current_y = min_y
                current_x += step

        bbox_list = list(generate_bounding_boxes(min_x, min_y, max_x, max_y, step_size))

        time_interval = (start_date, end_date)

        mode = 'all' if download_mode == 0 else 'monthly'
        
        config = SHConfig()
        config.sh_client_id = ""
        config.sh_client_secret = ""
        config.sh_token_url = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
        config.sh_base_url = "https://sh.dataspace.copernicus.eu"

        def process_data(config, bbox_coords, time_interval, download_mode, output_dir, feedback):
            resolution = 10
            aoi_bbox = BBox(bbox=bbox_coords, crs=CRS.WGS84)
            aoi_size = bbox_to_dimensions(aoi_bbox, resolution=resolution)
            catalog = SentinelHubCatalog(config=config)

            search_iterator = catalog.search(
                DataCollection.SENTINEL2_L2A,
                bbox=aoi_bbox,
                time=time_interval,
                filter=f"eo:cloud_cover < 20",
                fields={"include": ["id", "properties.datetime"], "exclude": []},
            )

            results = list(search_iterator)

            def parse_datetime(datetime_str):
                try:
                    return datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    return datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")

            df = pd.DataFrame([(item["id"], parse_datetime(item["properties"]["datetime"]).strftime("%Y-%m-%d")) for item in results],
                              columns=["ProductID", "Date"])

            if download_mode == "monthly":
                df['Month'] = df['Date'].apply(lambda x: x[:7])
                df = df.drop_duplicates(subset=["Month"])
                
            df['COMPLETED'] = 'NO'
            df.to_csv(f'{output_dir}/list_of_files.csv', index=False)

            for index, row in df.iterrows():
                product_id = row['ProductID']
                date = datetime.strptime(row['Date'], "%Y-%m-%d")
                start_date = (date - timedelta(days=1)).strftime("%Y-%m-%d")
                end_date = (date + timedelta(days=1)).strftime("%Y-%m-%d")

                request_all_bands = SentinelHubRequest(
                    data_folder=output_dir,
                    evalscript="""
                        //VERSION=3
                        function setup() {
                            return {
                                input: [{
                                    bands: ["B01","B02","B03","B04","B05","B06","B07","B08","B8A","B09","B11","B12"],
                                    units: "DN"
                                }],
                                output: {
                                    bands: 12,
                                    sampleType: "INT16"
                                }
                            }
                        }
                        function evaluatePixel(sample) {
                            return [sample.B01, sample.B02, sample.B03, sample.B04, sample.B05, sample.B06, sample.B07, sample.B08, sample.B8A, sample.B09, sample.B11, sample.B12];
                        }
                    """,
                    input_data=[
                        SentinelHubRequest.input_data(
                            data_collection=DataCollection.SENTINEL2_L2A,
                            time_interval=(start_date, end_date),
                        )
                    ],
                    responses=[
                        SentinelHubRequest.output_response('default', MimeType.TIFF)
                    ],
                    bbox=aoi_bbox,
                    size=aoi_size,
                    config=config
                )

                data = request_all_bands.get_data()

                if data:
                    row['COMPLETED'] = 'YES'
                else:
                    row['COMPLETED'] = 'NO'

            df.to_csv(f'{output_dir}/list_of_files.csv', index=False)
        
        for bbox_coords in bbox_list:
            process_data(config, bbox_coords, time_interval, mode, output_dir, feedback)

        return {}
