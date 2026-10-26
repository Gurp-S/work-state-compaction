import {createRoot} from 'react-dom/client';
import {UsagePageBody} from '@/components/A3SnapshotPanel';
import {ToastHost} from '@/components/ToastHost';
import '@/styles/entry.css';

// Host sizing only; no replacement UI, data adapters, or model-facing hints.
document.documentElement.style.height = '100%';
document.body.style.cssText = 'height:100%;margin:0;background:var(--xy-paper);color:var(--xy-ink)';
const root = document.getElementById('root')!;
root.style.cssText = 'height:100%;display:flex;flex-direction:column;min-width:0';
createRoot(root).render(<><UsagePageBody active /><ToastHost /></>);
