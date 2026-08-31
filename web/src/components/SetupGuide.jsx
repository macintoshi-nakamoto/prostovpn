import { GuideBody } from "./GuideBody.jsx";
import "./setup-guide.css";

export function SetupGuide({ login }) {
  return (
    <div className="sg">
      <GuideBody login={login} embedded />
    </div>
  );
}
