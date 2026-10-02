import { compileFromFile } from 'json-schema-to-typescript';
import { writeFile } from 'node:fs/promises';

const types = await compileFromFile('../src/contract_driven_ai_flow/schemas/project.json', { bannerComment: '/* Generated from Python ProjectSpec. Run scripts/export_schema.py; npm run types. */', additionalProperties: false });
await writeFile('src/generated.ts', types, 'utf8');
const research = await compileFromFile('../src/contract_driven_ai_flow/schemas/research.json', {bannerComment:'/* Generated from Python scientific wire models; scripts/export_schema.py + npm run types. */', additionalProperties:false});
await writeFile('src/research/generated.ts', research, 'utf8');
const models = await compileFromFile('../src/contract_driven_ai_flow/schemas/models.json', {bannerComment:'/* Generated from Python model profiles; scripts/export_schema.py + npm run types. */', additionalProperties:false});
await writeFile('src/settings/generated.ts',models,'utf8');
const workbench = await compileFromFile('../src/contract_driven_ai_flow/schemas/workbench.json', {bannerComment:'/* Generated from Python scientific workbench protocol v2; scripts/export_schema.py + npm run types. */', additionalProperties:false});
await writeFile('src/research/workspace/generated.ts',workbench,'utf8');
