import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import ReactECharts from 'echarts-for-react';
import type {Basin,Forecast} from './types';
import './style.css';

const api=async<T,>(path:string):Promise<T>=>{const response=await fetch(path);if(!response.ok)throw new Error(await response.text());return response.json()};

function ForecastChart({forecast,threshold}:{forecast:Forecast;threshold:number}){
 const dates=forecast.stage.map(p=>new Date(p.valid_at).toLocaleString([], {weekday:'short',hour:'numeric'}));
 const option={animation:false,tooltip:{trigger:'axis'},grid:{left:45,right:20,top:24,bottom:42},xAxis:{type:'category',data:dates,axisLabel:{color:'#90a6a0'}},yAxis:{type:'value',name:'Stage (ft)',axisLabel:{color:'#90a6a0'}},series:[{name:'90% low',type:'line',data:forecast.stage.map(p=>p.quantiles['0.05']),lineStyle:{opacity:0},stack:'band',symbol:'none'},{name:'90% interval',type:'line',data:forecast.stage.map(p=>p.quantiles['0.95']-p.quantiles['0.05']),lineStyle:{opacity:0},areaStyle:{color:'#3dd6b5',opacity:.2},stack:'band',symbol:'none'},{name:'Median stage',type:'line',data:forecast.stage.map(p=>p.quantiles['0.5']),smooth:true,lineStyle:{color:'#52e0bd',width:3},symbolSize:7,markLine:{silent:true,label:{formatter:'Minor stage'},lineStyle:{color:'#f5a65b',type:'dashed'},data:[{yAxis:threshold}]}}]};
 return <ReactECharts option={option} style={{height:330}}/>;
}

function App(){
 const [basins,setBasins]=useState<Basin[]>([]);const [selected,setSelected]=useState('');const [forecast,setForecast]=useState<Forecast|null>(null);const [error,setError]=useState('');
 useEffect(()=>{api<Basin[]>('/api/v1/basins').then(items=>{setBasins(items);setSelected(items[0]?.slug??'')}).catch(e=>setError(String(e)))},[]);
 useEffect(()=>{if(selected)api<Forecast>(`/api/v1/gauges/${selected}/forecast/latest`).then(setForecast).catch(()=>setForecast(null))},[selected]);
 const basin=basins.find(item=>item.slug===selected);const headline=forecast?.stage.filter(p=>[1,6,24].includes(p.horizon_hours))??[];
 return <main><header><div><span className="eyebrow">LOCAL RIVER INTELLIGENCE</span><h1>Hydro<span>Pulse</span></h1></div><div className="live"><i/> Local system</div></header>
  <section className="controls"><label>Forecast basin<select value={selected} onChange={e=>setSelected(e.target.value)}>{basins.map(b=><option value={b.slug} key={b.slug}>{b.target_name} · {b.river}</option>)}</select></label>{basin&&<div className="station">USGS {basin.usgs_id} · NOAA {basin.nwps_id}</div>}</section>
  {error&&<div className="notice error">{error}</div>}{!forecast&&<div className="empty"><h2>No forecast issued yet</h2><p>Start the collector or seed the development database, then issue a forecast with the local operator endpoint. Demo data is always labeled and is never used for scientific claims.</p></div>}
  {forecast&&basin&&<><section className="hero"><div><span className="eyebrow">LATEST FORECAST</span><h2>{basin.river} at {basin.target_name}</h2><p>Issued {new Date(forecast.issued_at).toLocaleString()} · observation age {Math.round(forecast.observation_age_minutes)} min</p></div><div className={`badge ${forecast.freshness}`}>{forecast.freshness}</div></section>
  <section className="cards">{headline.map(p=><article key={p.horizon_hours}><span>+{p.horizon_hours} hour{p.horizon_hours>1?'s':''}</span><strong>{p.quantiles['0.5'].toFixed(2)} <small>ft</small></strong><p>{p.quantiles['0.05'].toFixed(2)}–{p.quantiles['0.95'].toFixed(2)} ft interval</p></article>)}</section>
  <section className="panel"><div className="panel-title"><div><span className="eyebrow">STAGE TRAJECTORY</span><h3>Gauge height forecast</h3></div><span className="legend">Minor stage {basin.flood_stage_ft} ft</span></div><ForecastChart forecast={forecast} threshold={basin.flood_stage_ft}/></section>
  <section className="split"><div className="panel"><span className="eyebrow">EVIDENCE</span><h3>Flood-risk status</h3><p className="status">Insufficient independent events</p><p>Numerical estimates remain experimental. They cannot trigger validated flood-risk events.</p></div><div className="panel"><span className="eyebrow">PROVENANCE</span><h3>Forecast contract</h3><dl><dt>Stage model</dt><dd>{forecast.stage_model_version}</dd><dt>48/72h inputs</dt><dd>No future NWP</dd><dt>Snapshot</dt><dd>{forecast.id.slice(0,12)}</dd></dl></div></section></>}
  <footer>Gauge height is height above station datum, not river depth. HydroPulse is not an official warning service.</footer>
 </main>}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
