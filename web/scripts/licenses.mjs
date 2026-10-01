import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const destination = '../src/contract_driven_ai_flow/static/licenses';
await mkdir(destination, { recursive: true });
const lock = JSON.parse(await readFile('package-lock.json', 'utf8'));
const inventory = [];
for (const [directory, entry] of Object.entries(lock.packages)) {
  if (!directory.startsWith('node_modules/') || entry.dev) continue;
  const pkg = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
  const licenses = (await readdir(directory)).filter(file => /^licen[sc]e(?:\.|$)/i.test(file));
  for (const file of licenses) {
    await writeFile(path.join(destination, pkg.name.replaceAll('/', '__') + '-' + file), await readFile(path.join(directory, file)));
  }
  inventory.push({ name: pkg.name, version: pkg.version, license: pkg.license, repository: pkg.repository, license_files: licenses });
}
await writeFile(path.join(destination, 'sources.json'), JSON.stringify(inventory, null, 2));
console.log(`Distributed license texts for ${inventory.length} production dependencies`);
