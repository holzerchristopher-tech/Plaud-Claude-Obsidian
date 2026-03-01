import { build } from 'esbuild';
import { resolve } from 'path';

const entryPoints = [
    resolve(__dirname, 'src/main.ts'),
];

const outdir = resolve(__dirname, 'dist');

build({
    entryPoints,
    outdir,
    bundle: true,
    minify: true,
    sourcemap: true,
    platform: 'node',
    target: 'esnext',
    format: 'esm',
    loader: {
        '.ts': 'ts',
        '.css': 'text',
    },
}).catch(() => process.exit(1));