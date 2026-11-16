import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const identities={
  ledger:()=>api('/identities/ledger'),
  number:number=>api('/identities/numbers/'+encodeURIComponent(number)),
  operations:()=>api('/identities/operations'),
  conflicts:()=>api('/identities/conflicts'),
  jobs:()=>api('/identities/jobs'),
  merge:data=>api('/identities/merge',{method:'POST',body:JSON.stringify(data)}),
  split:data=>api('/identities/split',{method:'POST',body:JSON.stringify(data)}),
  register:data=>api('/identities/register',{method:'POST',body:JSON.stringify(data)}),
};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
