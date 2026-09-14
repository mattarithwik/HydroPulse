export type Basin={slug:string;name:string;target_name:string;usgs_id:string;nwps_id:string;flood_stage_ft:number;latitude:number;longitude:number;river:string};
export type Point={horizon_hours:number;valid_at:string;quantiles:Record<string,number>};
export type Risk={threshold_name:string;threshold_ft:number;horizon_hours:number;probability:number|null;method:string;evidence_status:string};
export type Forecast={id:string;target_id:string;issued_at:string;newest_observation_at:string;observation_age_minutes:number;stage_model_version:string;freshness:string;degradation_reasons:string[];stage:Point[];maximum_stage:Point[];risk:Risk[];horizon_model_mapping:Record<string,string>};
