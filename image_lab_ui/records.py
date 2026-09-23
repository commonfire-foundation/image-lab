"""Translate public analyzer results into the existing Image Lab storage format."""


def legacy_record(result, path):
    provenance = result['provenance']
    record = {'schema_version': 1, 'path': str(path), 'status': result['status'],
              'vision': result['predictions'], 'elapsed_seconds': result['elapsed_seconds']}
    if 'sha256' in result['input']:
        record['analysis'] = {k: v for k, v in result['input'].items() if k != 'path'}
        record['analysis'].update(result['measurements'] or {})
        # Keep policy/version/sampling evidence alongside legacy measurements.
        record['analysis_provenance'] = provenance
        record['analysis_schema_version'] = result['schema_version']
    if 'model' in provenance:
        record.update(model=provenance['model'], ollama_version=provenance['ollama_version'],
                      prompt=provenance['prompt'], prompt_version=provenance['profile_version'],
                      vision_settings=provenance['settings'])
    # Diagnostics must never overwrite validated prediction/path/status fields.
    record.update({key: value for key, value in result['diagnostics'].items()
                   if key in ('ollama_timing_ns', 'vision_response', 'vision_raw')})
    if result['error']:
        record.update(error=result['error']['message'], error_code=result['error']['code'])
    return record
