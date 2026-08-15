import { ROLES, type Role, type RoleBinding } from "./broker";
import type { BindingsState } from "./useBindings";

interface RoleBarProps {
  bindingsState: BindingsState;
  bindings: RoleBinding[];
  onPick: (role: Role) => void;
}

export function RoleBar({ bindingsState, bindings, onPick }: RoleBarProps) {
  if (bindingsState === "loading") {
    return <div className="roles">loading role bindings</div>;
  }

  if (bindingsState === "failed") {
    return <div className="roles">role bindings unavailable — model-broker is not running</div>;
  }

  return (
    <div className="roles">
      {ROLES.map((role) => {
        const binding = bindings.find((candidate) => candidate.role === role);

        return (
          <button type="button" className="role-chip" key={role} onClick={() => onPick(role)}>
            <span className="role-name">{role}</span>
            <span className={`role-model ${binding?.locality ?? "unbound"}`}>
              {binding?.model_id ?? "unbound"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
