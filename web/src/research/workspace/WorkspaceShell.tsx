import { useState, type Dispatch } from "react";
import { groups, type LayoutAction, type WorkspaceLayout } from "./layout";
import { Icon } from "./icons";
import "./workspace.css";

export function LayoutControls({
  layout,
  dispatch,
}: {
  layout: WorkspaceLayout;
  dispatch: Dispatch<LayoutAction>;
}) {
  const [menu, setMenu] = useState(false),
    [name, setName] = useState("");
  return (
    <div className="layout-controls">
      <button
        aria-label={layout.locked ? "解锁布局" : "锁定布局"}
        title={layout.locked ? "解锁布局" : "锁定布局"}
        aria-pressed={layout.locked}
        onClick={() => dispatch({ type: "lock", locked: !layout.locked })}
      >
        <Icon name="lock" />
      </button>
      <button onClick={() => setMenu(!menu)} aria-expanded={menu}>
        <Icon name="split" />
        布局
      </button>
      {menu && (
        <div className="workspace-menu">
          <button
            disabled={layout.locked}
            onClick={() =>
              dispatch({
                type: "split",
                group: layout.activeGroup,
                axis: "horizontal",
              })
            }
          >
            左右分屏
          </button>
          <button
            disabled={layout.locked}
            onClick={() =>
              dispatch({
                type: "split",
                group: layout.activeGroup,
                axis: "vertical",
              })
            }
          >
            上下分屏
          </button>
          <button
            disabled={layout.locked || groups(layout.tree).length < 2}
            onClick={() =>
              dispatch({ type: "remove-group", group: layout.activeGroup })
            }
          >
            合并当前分屏
          </button>
          <div className="preset-form">
            <input
              aria-label="布局名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="布局名称"
            />
            <button
              disabled={!name.trim()}
              onClick={() => {
                dispatch({ type: "save-preset", name });
                setMenu(false);
              }}
            >
              保存布局
            </button>
          </div>
          {Object.keys(layout.presets).map((preset) => (
            <button
              key={preset}
              aria-label={"恢复布局 " + preset}
              onClick={() => {
                dispatch({ type: "load-preset", name: preset });
                setMenu(false);
              }}
            >
              {preset}
            </button>
          ))}
          <button
            onClick={() => {
              dispatch({ type: "reset" });
              setMenu(false);
            }}
          >
            恢复默认布局
          </button>
        </div>
      )}
    </div>
  );
}

export { DockWorkspaceShell as WorkspaceShell } from "./DockWorkspaceShell";
