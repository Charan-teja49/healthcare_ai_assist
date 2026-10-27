import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./e2e',timeout:180000,use:{baseURL:'http://127.0.0.1:5174',headless:true,trace:'retain-on-failure'},workers:1,reporter:'list'});
