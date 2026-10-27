import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{port:Number(process.env.MEDIASSIST_FRONTEND_PORT||5174),strictPort:true,proxy:{'/api':process.env.MEDIASSIST_API_TARGET||'http://127.0.0.1:8010','/ws':{target:process.env.MEDIASSIST_API_TARGET||'http://127.0.0.1:8010',ws:true}}}});
