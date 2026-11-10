import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import plugin from '../plugin/index.mjs';

function registered() {
  const tools = [], routes = [], services = [], commands = [], descriptors = [];
  plugin.register({ pluginConfig: { stateDir: '/tmp/workbench-test-no-secrets' }, logger: {},
    registerTool: t => tools.push(t), registerHttpRoute: r => routes.push(r), registerService: s => services.push(s),
    registerCommand: c => commands.push(c), registerControlUiDescriptor: d => descriptors.push(d) });
  return { tools, routes, services, commands, descriptors };
}
test('manifest owns every registered tool and exposes the local UI', () => {
  const manifest = JSON.parse(readFileSync(new URL('../plugin/openclaw.plugin.json', import.meta.url)));
  const { tools, routes, services, commands, descriptors } = registered();
  assert.deepEqual(tools.map(t => t.name).sort(), [...manifest.contracts.tools].sort());
  assert.equal(new Set(tools.map(t => t.name)).size, 10);
  assert.equal(routes[0].path, '/workbench');
  assert.equal(services.length, 1); assert.equal(commands[0].name, 'workbench');
  assert.equal(descriptors[0].schema.url, '/workbench/');
});
test('agent transitions have no human approval, reception or terminal control', () => {
  const { tools } = registered();
  const transition = tools.find(t => t.name === 'workbench_transition');
  assert.deepEqual(transition.parameters.properties.action.enum, ['start-analysis', 'propose-plan', 'verify', 'block']);
  assert.ok(tools.every(t => !/approve|receive|terminal|confirm/.test(t.name)));
  assert.equal(transition.parameters.additionalProperties, false);
});
test('HTTP proxy rejects non-loopback callers before any upstream request', async () => {
  const { routes } = registered();
  let code, body;
  await routes[0].handler({ socket: { remoteAddress: '192.0.2.4' } }, { writeHead(c) { code = c; }, end(v) { body = v; } });
  assert.equal(code, 403); assert.match(body, /locale/);
});
