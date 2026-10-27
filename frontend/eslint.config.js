import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
export default [
 {ignores:['dist/**','node_modules/**','tools-*.mjs']},
 {files:['src/**/*.js','src/**/*.jsx','*.js'],...js.configs.recommended,
 languageOptions:{ecmaVersion:'latest',sourceType:'module',parserOptions:{ecmaFeatures:{jsx:true}},globals:{...globals.browser,...globals.node}},
 plugins:{react},rules:{'react/jsx-uses-react':'error','react/jsx-uses-vars':'error','react/jsx-no-undef':'error','no-unused-vars':['error',{argsIgnorePattern:'^_'}]}}
];
