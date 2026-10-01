import { compileFromFile } from 'json-schema-to-typescript';
import { writeFile } from 'node:fs/promises';

const types = await compileFromFile('../src/contract_driven_ai_flow/schemas/project.json', { bannerComment: '/* Generated from Python ProjectSpec. Run scripts/export_schema.py; npm run types. */', additionalProperties: false });
await writeFile('src/generated.ts', types, 'utf8');
