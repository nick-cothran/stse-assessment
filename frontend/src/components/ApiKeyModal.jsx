import { useEffect, useRef, useState } from "react";
import "./ApiKeyModal.css";
import axios from "axios";

export default function ApiKeyModal({ onClose, onKeySaved, providers }) {
  const [errorMsg, setErrorMsg] = useState("");

  return (
    <div className="modal-blur" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Set your API keys</h2>
          <button className="close-btn" onClick={onClose}>
            ✖
          </button>
        </div>
        {errorMsg && <div className="error-msg">{errorMsg}</div>}
        {providers.map((p) => (
          <KeyInput
            key={p.value}
            provider={p}
            onKeySaved={onKeySaved}
            setError={setErrorMsg}
          />
        ))}
      </div>
    </div>
  );
}

function KeyInput({ provider, onKeySaved, setError }) {
  const [isConfirmed, setIsConfirmed] = useState(provider.isAvailable);
  const [value, setValue] = useState("");

  async function saveKey(provider, key) {
    setError("");
    try {
      await axios.post("/api/keys", { provider: provider, key: key });
      await onKeySaved();
      setValue("");
      setIsConfirmed(true);
    } catch (err) {
      setError(`Error saving key: ${err.response?.data?.detail}`);
    }
  }
  async function deleteKey(provider) {
    setError("");
    try {
      await axios.delete(`/api/keys/${provider}`);
      await onKeySaved();
      setValue("");
      setIsConfirmed(false);
    } catch (err) {
      setError(`Error removing key: ${err.response?.data?.detail}`);
    }
  }

  return (
    <div className="key-ctn">
      <p className="model-header">{provider.label}</p>
      <div className="input-ctn">
        {isConfirmed ? (
          <>
            <p>API key is set</p>
            <button
              className="key-input-btn confirm-btn"
              onClick={() => setIsConfirmed(false)}
            >
              Change key
            </button>
            <button
              className="key-input-btn cancel-btn"
              onClick={() => deleteKey(provider.value)}
            >
              Remove key
            </button>
          </>
        ) : (
          <>
            <p>Enter key: </p>
            <input
              value={value}
              type="password"
              onChange={(e) => setValue(e.target.value)}
            ></input>
            <button
              className="key-input-btn confirm-btn"
              onClick={() => saveKey(provider.value, value)}
              disabled={!value}
            >
              Save
            </button>
            {provider.isAvailable && (
              <button
                className="key-input-btn cancel-btn"
                onClick={() => {
                  setValue("");
                  setIsConfirmed(true);
                }}
              >
                Cancel
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
