import { useRef, useState, type Dispatch, type ReactNode } from 'react';
import { groups, type Group, type LayoutAction, type LayoutNode, type Split, type WorkspaceDocument, type WorkspaceLayout } from './layout';
import { Icon } from './icons';
import './workspace.css';

export function LayoutControls({ layout, dispatch }: { layout: WorkspaceLayout; dispatch: Dispatch<LayoutAction> }) {
  const [menu, setMenu] = useState(false), [name, setName] = useState('');
  return <div className="layout-controls">
    <button aria-label={layout.locked ? '解锁布局' : '锁定布局'} title={layout.locked ? '解锁布局' : '锁定布局'} aria-pressed={layout.locked} onClick={() => dispatch({ type: 'lock', locked: !layout.locked })}><Icon name="lock" /></button>
    <button onClick={() => setMenu(!menu)} aria-expanded={menu}><Icon name="split" />布局</button>
    {menu && <div className="workspace-menu">
      <button disabled={layout.locked} onClick={() => dispatch({ type: 'split', group: layout.activeGroup, axis: 'horizontal' })}>左右分屏</button>
      <button disabled={layout.locked} onClick={() => dispatch({ type: 'split', group: layout.activeGroup, axis: 'vertical' })}>上下分屏</button>
      <button disabled={layout.locked || groups(layout.tree).length < 2} onClick={() => dispatch({ type: 'remove-group', group: layout.activeGroup })}>合并当前分屏</button>
      <div className="preset-form"><input aria-label="布局名称" value={name} onChange={e => setName(e.target.value)} placeholder="布局名称" /><button disabled={!name.trim()} onClick={() => { dispatch({ type: 'save-preset', name }); setMenu(false); }}>保存布局</button></div>
      {Object.keys(layout.presets).map(preset => <button key={preset} aria-label={'恢复布局 ' + preset} onClick={() => { dispatch({ type: 'load-preset', name: preset }); setMenu(false); }}>{preset}</button>)}
      <button onClick={() => { dispatch({ type: 'reset' }); setMenu(false); }}>恢复默认布局</button>
    </div>}
  </div>;
}

function Separator({ node, dispatch, disabled }: { node: Split; dispatch: Dispatch<LayoutAction>; disabled: boolean }) {
  const dragging = useRef(false);
  const resize = (element: HTMLElement, x: number, y: number) => {
    const box = element.parentElement!.getBoundingClientRect();
    dispatch({ type: 'resize', id: node.id, ratio: node.axis === 'horizontal' ? (x - box.x) / box.width : (y - box.y) / box.height });
  };
  return <div className={'workspace-separator ' + node.axis} role="separator" aria-label={'调整 ' + node.id + ' 分屏'} aria-orientation={node.axis === 'horizontal' ? 'vertical' : 'horizontal'} aria-valuenow={Math.round(node.ratio * 100)} aria-valuemin={15} aria-valuemax={85} aria-disabled={disabled} tabIndex={disabled ? -1 : 0}
    onPointerDown={e => { if (!disabled) { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); e.preventDefault(); } }}
    onPointerMove={e => { if (dragging.current && !disabled) resize(e.currentTarget, e.clientX, e.clientY); }}
    onPointerUp={() => { dragging.current = false; }} onLostPointerCapture={() => { dragging.current = false; }}
    onKeyDown={e => { if (disabled) return; const forward = node.axis === 'horizontal' ? 'ArrowRight' : 'ArrowDown', backward = node.axis === 'horizontal' ? 'ArrowLeft' : 'ArrowUp';
      if ([forward, backward, 'Home', 'End'].includes(e.key)) { e.preventDefault(); dispatch({ type: 'resize', id: node.id, ratio: e.key === 'Home' ? .15 : e.key === 'End' ? .85 : node.ratio + (e.key === forward ? .025 : -.025) }); } }} />;
}

export function WorkspaceShell({ layout, dispatch, render, onOpen }: { layout: WorkspaceLayout; dispatch: Dispatch<LayoutAction>; render: (doc: WorkspaceDocument) => ReactNode; onOpen: () => void }) {
  const drawGroup = (group: Group) => {
    const active = group.active ? layout.documents[group.active] : null;
    return <section key={group.id} className={'workspace-group' + (layout.focused && layout.focused !== group.id ? ' focus-hidden' : '') + (group.minimized ? ' minimized' : '')} data-group={group.id}
      onDragOver={e => { e.preventDefault(); }} onDrop={e => { e.preventDefault(); const id = e.dataTransfer.getData('application/cdaf-document'); if (id) dispatch({ type: 'move', documentId: id, group: group.id }); }}>
      <div className="workspace-tabs" role="tablist" aria-label={group.id + ' 视图'}>
        <div className="workspace-tab-scroll">{group.tabs.map(id => { const doc = layout.documents[id]; return <div key={id} className={'workspace-tab' + (group.active === id ? ' active' : '')} draggable onDragStart={e => e.dataTransfer.setData('application/cdaf-document', id)}>
          <button role="tab" aria-selected={group.active === id} title={doc.title} onDoubleClick={() => dispatch({ type: 'pin', documentId: id, pinned: true })} onClick={() => dispatch({ type: 'activate', group: group.id, documentId: id })}><Icon name={doc.kind} /><span>{doc.title}</span>{doc.pinned && <Icon name="pin" size={12} />}</button>
          <button className="workspace-icon-button" aria-label={'关闭 ' + doc.title} title="关闭视图" onClick={() => dispatch({ type: 'close', documentId: id })}><Icon name="close" size={12} /></button>
        </div>; })}</div>
        <div className="workspace-pane-actions">
          {active && <button className="workspace-icon-button" title={active.pinned ? '解除版本固定' : '固定当前对象版本'} aria-label={active.pinned ? '解除版本固定' : '固定当前对象版本'} aria-pressed={active.pinned} onClick={() => dispatch({ type: 'pin', documentId: active.id, pinned: !active.pinned })}><Icon name="pin" size={13} /></button>}
          <button className="workspace-icon-button" aria-label={(group.minimized ? '恢复 ' : '缩小 ') + group.id + ' 视图'} title={group.minimized ? '恢复视图' : '缩小视图'} onClick={() => dispatch({ type: 'minimize', group: group.id, minimized: !group.minimized })}><Icon name={group.minimized ? 'restore' : 'minimize'} size={13} /></button>
          <button className="workspace-icon-button" aria-label={(layout.focused === group.id ? '还原 ' : '放大 ') + group.id + ' 视图'} title={layout.focused === group.id ? '还原视图' : '放大视图'} onClick={() => dispatch({ type: 'focus', group: layout.focused === group.id ? null : group.id })}><Icon name={layout.focused === group.id ? 'restore' : 'maximize'} size={13} /></button>
        </div>
      </div>
      <div className="workspace-document" hidden={group.minimized} role="tabpanel" aria-label={active?.title ?? '空视图'}>
        {active ? render(active) : <div className="workspace-empty"><button onClick={onOpen}><Icon name="add" />打开视图</button></div>}
      </div>
      {group.minimized && <button className="minimized-restore" onClick={() => dispatch({ type: 'minimize', group: group.id, minimized: false })}>恢复 {active?.title ?? '视图'}</button>}
    </section>;
  };
  const tree = (node: LayoutNode): ReactNode => {
    if (node.type === 'group') return drawGroup(node);
    const firstMin = groups(node.first).every(g => g.minimized), secondMin = groups(node.second).every(g => g.minimized);
    return <div className={'workspace-split ' + node.axis} data-split={node.id} key={node.id}>
      <div className="workspace-child" style={{ flex: !layout.locked && firstMin ? '0 0 34px' : `${node.ratio} 1 0` }}>{tree(node.first)}</div>
      <Separator node={node} dispatch={dispatch} disabled={layout.locked || firstMin || secondMin || !!layout.focused} />
      <div className="workspace-child" style={{ flex: !layout.locked && secondMin ? '0 0 34px' : `${1 - node.ratio} 1 0` }}>{tree(node.second)}</div>
    </div>;
  };
  return <div className={'workspace-shell' + (layout.focused ? ' is-focused' : '')}>{tree(layout.tree)}</div>;
}
