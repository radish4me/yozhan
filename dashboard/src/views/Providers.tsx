import { api } from "../api";
import { useAsync } from "../useAsync";
import { Async, Panel } from "./Panel";

export function Providers() {
  const providers = useAsync(() => api.providers());

  return (
    <Panel
      title="Providers"
      subtitle="Configured in config/providers.yaml. Key values are never sent to the dashboard — only whether each is present."
    >
      <Async state={providers}>
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Type</th>
                <th>Models</th>
                <th>Keys</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((provider) => {
                const needsKeys = provider.keys_declared > 0;
                const healthy = !needsKeys || provider.keys_configured > 0;
                return (
                  <tr key={provider.name}>
                    <td>{provider.name}</td>
                    <td className="muted">{provider.type}</td>
                    <td>
                      {provider.models.map((model) => (
                        <span className="tag" key={model}>
                          {model}
                        </span>
                      ))}
                    </td>
                    <td className={healthy ? "ok" : "error"}>
                      {needsKeys
                        ? `${provider.keys_configured}/${provider.keys_declared} set`
                        : "none needed"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Async>
    </Panel>
  );
}
