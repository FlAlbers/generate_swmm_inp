# -*- coding: utf-8 -*-
"""
Build SWMM-ready layers from non-standard GIS layers using Processing.
"""
from typing import Dict, List, Tuple
from qgis.PyQt.QtCore import QVariant, QCoreApplication
from qgis.core import (
    QgsFeature,
    QgsFields,
    QgsField,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterField,
    QgsProcessingParameterVectorDestination,
    QgsProcessingParameterVectorLayer,
)
from .g_s_defaults import def_qgis_fields_dict


def _tr(message: str) -> str:
    """Translate helper."""
    return QCoreApplication.translate('SwmmLayerBuilder', message)


class SwmmLayerBuilderAlgorithm(QgsProcessingAlgorithm):
    """
    Generic builder that maps an input layer into the SWMM schema for a given section.
    """
    def __init__(self, section_key: str, display_name: str, geom_type: str):
        super().__init__()
        self.section_key = section_key
        self._display_name = display_name
        self.geom_type = geom_type
        self.INPUT_LAYER = "INPUT_LAYER"
        self.OUTPUT = "OUTPUT"
        # tuples: (param_id, label, target_field, required_bool)
        self.field_params: List[Tuple[str, str, str, bool]] = self._field_definitions(section_key)

    def initAlgorithm(self, config=None):
        """Declare input layer, output sink, and per-field mapping parameters."""
        geom_param_type = {
            'Point': [QgsProcessing.SourceType.TypeVectorPoint],
            'LineString': [QgsProcessing.SourceType.TypeVectorLine],
            'Polygon': [QgsProcessing.SourceType.TypeVectorPolygon],
        }[self.geom_type]

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT_LAYER,
                _tr(f"Input {self.geom_type} layer"),
                geom_param_type
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                _tr("SWMM layer output")
            )
        )
        for param_id, label, target_field, required in self.field_params:
            self.addParameter(
                QgsProcessingParameterField(
                    param_id,
                    _tr(label),
                    parentLayerParameterName=self.INPUT_LAYER,
                    optional=not required,
                    defaultValue=target_field  # prefer auto-match by name if present
                )
            )

    def name(self):
        return f"Build{self.section_key.capitalize()}"

    def displayName(self):
        return _tr(self._display_name)

    def group(self):
        return _tr("Build SWMM Layers (from non standard Layers)")

    def groupId(self):
        return "build_swmm_layers"

    def shortHelpString(self):
        return _tr(f"Creates a SWMM-ready {self.section_key.lower()} layer with required fields.")

    def createInstance(self):
        return SwmmLayerBuilderAlgorithm(self.section_key, self._display_name, self.geom_type)

    def processAlgorithm(self, parameters, context, feedback):
        """Create an output layer with SWMM fields, mapping user-selected or auto-matched fields."""
        input_layer = self.parameterAsVectorLayer(parameters, self.INPUT_LAYER, context)
        if input_layer is None:
            raise QgsProcessingException(_tr("Input layer is required."))

        field_map = {}
        layer_field_names = input_layer.fields().names()
        for param_id, _, target_field, _ in self.field_params:
            param_val = self.parameterAsString(parameters, param_id, context)
            if not param_val and target_field in layer_field_names:
                # auto-select if the layer already has a matching field name
                param_val = target_field
            field_map[target_field] = param_val

        target_fields_def = def_qgis_fields_dict[self.section_key]
        type_map = {
            'Double': QVariant.Double,
            'String': QVariant.String,
            'Int': QVariant.Int,
            'Bool': QVariant.Bool,
            'Date': QVariant.Date,
            'Time': QVariant.Time
        }
        target_fields = QgsFields()
        for name, typ in target_fields_def.items():
            target_fields.append(QgsField(name, type_map[typ]))

        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            target_fields,
            input_layer.wkbType(),
            input_layer.sourceCrs()
        )
        if sink is None:
            raise QgsProcessingException(_tr("Could not create output sink."))

        defaults = self._defaults_for_section(self.section_key)

        total = input_layer.featureCount()
        for idx, feature in enumerate(input_layer.getFeatures()):
            attrs = [
                self._value_from_feature(feature, field_map.get(field), defaults.get(field))
                for field in target_fields_def.keys()
            ]
            out_feat = QgsFeature(target_fields)
            out_feat.setGeometry(feature.geometry())
            out_feat.setAttributes(attrs)
            sink.addFeature(out_feat)

            if feedback.isCanceled():
                break
            if total:
                feedback.setProgress(int((idx + 1) / total * 100))

        return {self.OUTPUT: dest_id}

    def _defaults_for_section(self, section: str) -> Dict[str, object]:
        """Fallback values when a field is missing or empty in the source."""
        if section == 'SUBCATCHMENTS':
            return {
                'Name': '',
                'RainGage': '*',
                'Outlet': '',
                'Area': 0,
                'Imperv': 0,
                'Width': 0,
                'Slope': 0.5,
                'CurbLen': 0,
                'SnowPack': '',
                'N_Imperv': 0.01,
                'N_Perv': 0.1,
                'S_Imperv': 1.8,
                'S_Perv': 3,
                'PctZero': 0,
                'RouteTo': 'OUTLET',
                'PctRouted': 100,
                'InfMethod': '',
                'SuctHead': None,
                'Conductiv': None,
                'InitDef': None,
                'MaxRate': None,
                'MinRate': None,
                'Decay': None,
                'DryTime': None,
                'MaxInf': None,
                'CurveNum': None
            }
        if section == 'JUNCTIONS':
            return {
                'Name': '',
                'Elevation': 0,
                'MaxDepth': 0,
                'InitDepth': 0,
                'SurDepth': 0,
                'Aponded': 0
            }
        if section == 'OUTFALLS':
            return {
                'Name': '',
                'Elevation': 0,
                'Type': 'FREE',
                'FixedStage': None,
                'Curve_TS': '',
                'FlapGate': '',
                'RouteTo': ''
            }
        if section == 'RAINGAGES':
            return {
                'Name': '',
                'Format': '',
                'Interval': '',
                'SCF': 1.0,
                'DataSource': '',
                'SeriesName': '',
                'FileName': '',
                'StationID': '',
                'RainUnits': ''
            }
        if section == 'STORAGE':
            return {k: 0 if v == 'Double' else '' for k, v in def_qgis_fields_dict['STORAGE'].items()}
        if section == 'CONDUITS':
            return {
                'Name': '',
                'FromNode': '',
                'ToNode': '',
                'Length': 0,
                'Roughness': 0.01,
                'InOffset': 0,
                'OutOffset': 0,
                'InitFlow': 0,
                'MaxFlow': 0,
                'XsectShape': '',
                'Geom1': 0,
                'Geom2': 0,
                'Geom3': 0,
                'Geom4': 0,
                'Barrels': 1,
                'Culvert': '',
                'Shp_Trnsct': '',
                'Kentry': 0,
                'Kexit': 0,
                'Kavg': 0,
                'FlapGate': '',
                'Seepage': 0
            }
        if section == 'ORIFICES':
            return {
                'Name': '',
                'FromNode': '',
                'ToNode': '',
                'Type': '',
                'InOffset': 0,
                'Qcoeff': 0,
                'FlapGate': '',
                'CloseTime': 0,
                'XsectShape': '',
                'Height': 0,
                'Width': 0
            }
        if section == 'PUMPS':
            return {
                'Name': '',
                'FromNode': '',
                'ToNode': '',
                'PumpCurve': '',
                'Status': '',
                'Startup': 0,
                'Shutoff': 0
            }
        if section == 'WEIRS':
            return {
                'Name': '',
                'FromNode': '',
                'ToNode': '',
                'Type': '',
                'CrestHeigh': 0,
                'Qcoeff': 0,
                'FlapGate': '',
                'EndContrac': 0,
                'EndCoeff': 0,
                'Surcharge': '',
                'RoadWidth': 0,
                'RoadSurf': '',
                'CoeffCurve': '',
                'Height': 0,
                'Length': 0,
                'SideSlope': 0
            }
        return {k: None for k in def_qgis_fields_dict[section].keys()}

    def _field_definitions(self, section: str) -> List[Tuple[str, str, str, bool]]:
        """Define which SWMM fields can be mapped per section (param id, label, target, required)."""
        if section == 'JUNCTIONS':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('ELEV_FIELD', 'Elevation field', 'Elevation', True),
                ('MAXDEPTH_FIELD', 'MaxDepth field', 'MaxDepth', True),
                ('INITDEPTH_FIELD', 'InitDepth field', 'InitDepth', False),
                ('SURDEPTH_FIELD', 'SurDepth field', 'SurDepth', False),
                ('APONDED_FIELD', 'Aponded field', 'Aponded', False),
            ]
        if section == 'OUTFALLS':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('ELEV_FIELD', 'Elevation field', 'Elevation', True),
                ('TYPE_FIELD', 'Type field', 'Type', True),
                ('FIXED_FIELD', 'FixedStage field', 'FixedStage', False),
                ('CURVE_FIELD', 'Curve_TS field', 'Curve_TS', False),
                ('FLAP_FIELD', 'FlapGate field', 'FlapGate', False),
                ('ROUTETO_FIELD', 'RouteTo field', 'RouteTo', False),
            ]
        if section == 'RAINGAGES':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('FORMAT_FIELD', 'Format field', 'Format', True),
                ('INTERVAL_FIELD', 'Interval field', 'Interval', True),
                ('SCF_FIELD', 'SCF field', 'SCF', False),
                ('DATASRC_FIELD', 'DataSource field', 'DataSource', False),
                ('SERIES_FIELD', 'SeriesName field', 'SeriesName', False),
                ('FILE_FIELD', 'FileName field', 'FileName', False),
                ('STATION_FIELD', 'StationID field', 'StationID', False),
                ('RAINUNITS_FIELD', 'RainUnits field', 'RainUnits', False),
            ]
        if section == 'STORAGE':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('ELEV_FIELD', 'Elevation field', 'Elevation', True),
                ('MAXDEPTH_FIELD', 'MaxDepth field', 'MaxDepth', True),
                ('INITDEPTH_FIELD', 'InitDepth field', 'InitDepth', False),
                ('TYPE_FIELD', 'Type field', 'Type', False),
                ('CURVE_FIELD', 'Curve field', 'Curve', False),
                ('COEFF_FIELD', 'Coeff field', 'Coeff', False),
                ('EXP_FIELD', 'Exponent field', 'Exponent', False),
                ('CONST_FIELD', 'Constant field', 'Constant', False),
                ('MAJORAX_FIELD', 'MajorAxis field', 'MajorAxis', False),
                ('MINORAX_FIELD', 'MinorAxis field', 'MinorAxis', False),
                ('SIDESLOPE_FIELD', 'SideSlope field', 'SideSlope', False),
                ('SURFHEIGHT_FIELD', 'SurfHeight field', 'SurfHeight', False),
                ('SURDEPTH_FIELD', 'SurDepth field', 'SurDepth', False),
                ('FEVAP_FIELD', 'Fevap field', 'Fevap', False),
                ('PSI_FIELD', 'Psi field', 'Psi', False),
                ('KSAT_FIELD', 'Ksat field', 'Ksat', False),
                ('IMD_FIELD', 'IMD field', 'IMD', False),
            ]
        if section == 'CONDUITS':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('FROM_FIELD', 'FromNode field', 'FromNode', True),
                ('TO_FIELD', 'ToNode field', 'ToNode', True),
                ('LENGTH_FIELD', 'Length field', 'Length', True),
                ('ROUGH_FIELD', 'Roughness field', 'Roughness', False),
                ('INOFF_FIELD', 'InOffset field', 'InOffset', False),
                ('OUTOFF_FIELD', 'OutOffset field', 'OutOffset', False),
                ('INITFLOW_FIELD', 'InitFlow field', 'InitFlow', False),
                ('MAXFLOW_FIELD', 'MaxFlow field', 'MaxFlow', False),
                ('XSECTSHAPE_FIELD', 'XsectShape field', 'XsectShape', False),
                ('GEOM1_FIELD', 'Geom1 field', 'Geom1', False),
                ('GEOM2_FIELD', 'Geom2 field', 'Geom2', False),
                ('GEOM3_FIELD', 'Geom3 field', 'Geom3', False),
                ('GEOM4_FIELD', 'Geom4 field', 'Geom4', False),
                ('BARRELS_FIELD', 'Barrels field', 'Barrels', False),
                ('CULVERT_FIELD', 'Culvert field', 'Culvert', False),
                ('SHPTRNS_FIELD', 'Shp_Trnsct field', 'Shp_Trnsct', False),
                ('KENTRY_FIELD', 'Kentry field', 'Kentry', False),
                ('KEXIT_FIELD', 'Kexit field', 'Kexit', False),
                ('KAVG_FIELD', 'Kavg field', 'Kavg', False),
                ('FLAP_FIELD', 'FlapGate field', 'FlapGate', False),
                ('SEEP_FIELD', 'Seepage field', 'Seepage', False),
            ]
        if section == 'ORIFICES':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('FROM_FIELD', 'FromNode field', 'FromNode', True),
                ('TO_FIELD', 'ToNode field', 'ToNode', True),
                ('TYPE_FIELD', 'Type field', 'Type', True),
                ('INOFF_FIELD', 'InOffset field', 'InOffset', False),
                ('QCOEFF_FIELD', 'Qcoeff field', 'Qcoeff', False),
                ('FLAP_FIELD', 'FlapGate field', 'FlapGate', False),
                ('CLOSETIME_FIELD', 'CloseTime field', 'CloseTime', False),
                ('XSECTSHAPE_FIELD', 'XsectShape field', 'XsectShape', False),
                ('HEIGHT_FIELD', 'Height field', 'Height', False),
                ('WIDTH_FIELD', 'Width field', 'Width', False),
            ]
        if section == 'PUMPS':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('FROM_FIELD', 'FromNode field', 'FromNode', True),
                ('TO_FIELD', 'ToNode field', 'ToNode', True),
                ('CURVE_FIELD', 'PumpCurve field', 'PumpCurve', True),
                ('STATUS_FIELD', 'Status field', 'Status', False),
                ('STARTUP_FIELD', 'Startup field', 'Startup', False),
                ('SHUTOFF_FIELD', 'Shutoff field', 'Shutoff', False),
            ]
        if section == 'WEIRS':
            return [
                ('NAME_FIELD', 'Name field', 'Name', True),
                ('FROM_FIELD', 'FromNode field', 'FromNode', True),
                ('TO_FIELD', 'ToNode field', 'ToNode', True),
                ('TYPE_FIELD', 'Type field', 'Type', True),
                ('CREST_FIELD', 'CrestHeigh field', 'CrestHeigh', False),
                ('QCOEFF_FIELD', 'Qcoeff field', 'Qcoeff', False),
                ('FLAP_FIELD', 'FlapGate field', 'FlapGate', False),
                ('ENDCONTR_FIELD', 'EndContrac field', 'EndContrac', False),
                ('ENDCOEFF_FIELD', 'EndCoeff field', 'EndCoeff', False),
                ('SURCH_FIELD', 'Surcharge field', 'Surcharge', False),
                ('ROADWIDTH_FIELD', 'RoadWidth field', 'RoadWidth', False),
                ('ROADSURF_FIELD', 'RoadSurf field', 'RoadSurf', False),
                ('COEFFCURVE_FIELD', 'CoeffCurve field', 'CoeffCurve', False),
                ('HEIGHT_FIELD', 'Height field', 'Height', False),
                ('LENGTH_FIELD', 'Length field', 'Length', False),
                ('SIDESLOPE_FIELD', 'SideSlope field', 'SideSlope', False),
            ]
        return []

    def _value_from_feature(self, feature, field_name, default_val):
        """Get a value from a feature field, falling back to default when missing/empty."""
        if field_name and field_name in feature.fields().names():
            val = feature[field_name]
            if val not in [None, '']:
                return val
        return default_val
