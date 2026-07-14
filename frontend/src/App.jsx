import React, { useState, useEffect, useRef } from 'react';

const API_BASE = 'http://localhost:8000';

function App() {
  const [nodes, setNodes] = useState([
    { id: 'step_1', type: 'click', x: 100, y: 200, delay: 1.0, next: 'end', loopId: 'Loop_1' }
  ]);
  const [status, setStatus] = useState({ is_running: false, current_step: null });
  const [serverLogs, setServerLogs] = useState([]);
  const [isWaiting, setIsWaiting] = useState(false);

  const [saveFilename, setSaveFilename] = useState("my_macro");
  const [restInterval, setRestInterval] = useState(0);
  const [restDuration, setRestDuration] = useState(0);
  const [stopDelaySteps, setStopDelaySteps] = useState(0);

  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [scriptList, setScriptList] = useState([]);
  const [selectedScript, setSelectedScript] = useState("");

  const terminalRef = useRef(null);

  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [serverLogs]);

  const fetchScripts = async () => {
    try {
      const res = await fetch(`${API_BASE}/list_scripts`);
      if (res.ok) {
        const data = await res.json();
        setScriptList(data.scripts || []);
        if (data.scripts && data.scripts.length > 0 && !selectedScript) {
          setSelectedScript(data.scripts[0]);
        }
      }
    } catch (err) { }
  };

  useEffect(() => {
    fetchScripts();
    fetch(`${API_BASE}/get_telegram_config`)
      .then(res => res.json())
      .then(data => {
         if(data.bot_token) setBotToken(data.bot_token);
         if(data.chat_id) setChatId(data.chat_id);
      })
      .catch(err => console.error(err));
  }, []);

  useEffect(() => {
    const statusInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/status`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data);
        }
      } catch (err) { }
    }, 1000);

    const logsInterval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/logs`);
        if (res.ok) {
          const data = await res.json();
          setServerLogs(data.logs || []);
        }
      } catch (err) { }
    }, 1000);

    return () => {
      clearInterval(statusInterval);
      clearInterval(logsInterval);
    };
  }, []);

  const handleStart = async () => {
    try {
      await fetch(`${API_BASE}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            start_step: 'step_1', 
            rest_interval_min: parseFloat(restInterval) || 0, 
            rest_duration_sec: parseFloat(restDuration) || 0,
            stop_delay_steps: parseInt(stopDelaySteps) || 0
        })
      });
    } catch (e) {
      console.error(e);
    }
  };

  const handleStop = async () => {
    try {
      await fetch(`${API_BASE}/stop`, { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeploy = async () => {
    const script = {};
    nodes.forEach(n => {
      const { id, type, loopId, ...rest } = n;
      script[id] = { type, ...rest };
    });

    try {
      await fetch(`${API_BASE}/load_script`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script })
      });
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveFile = async () => {
    const script = {};
    nodes.forEach(n => {
      const { id, ...rest } = n;
      script[id] = rest;
    });
    try {
      const res = await fetch(`${API_BASE}/save_script_file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: saveFilename, script })
      });
      if (res.ok) {
        fetchScripts();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveTelegram = async () => {
    try {
      await fetch(`${API_BASE}/save_telegram_config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot_token: botToken, chat_id: chatId })
      });
      alert("Telegram Config Saved! Bot is now active.");
    } catch (e) {
      console.error(e);
    }
  };

  const handleLoadFile = async () => {
    if (!selectedScript) return;
    try {
      const res = await fetch(`${API_BASE}/get_script/${selectedScript}`);
      if (res.ok) {
        const data = await res.json();
        const loadedNodes = Object.keys(data).map(id => ({ id, ...data[id] }));
        setNodes(loadedNodes);
        setSaveFilename(selectedScript.replace('.json', ''));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const addNode = (type) => {
    const id = `step_${nodes.length + 1}`;
    let newNode = { id, type, loopId: 'Loop_1' };
    if (type === 'click') {
      newNode = { ...newNode, x: 0, y: 0, delay: 1.0, next: 'end' };
    } else if (type === 'wait') {
      newNode = { ...newNode, type: 'click', x: 0, y: 0, delay: 5.0, next: 'end' };
    } else if (type === 'keypress') {
      newNode = { ...newNode, key: 'enter', delay: 1.0, next: 'end' };
    } else if (type === 'check_image') {
      newNode = {
        ...newNode,
        bbox: { left: 0, top: 0, width: 100, height: 100 },
        baseline: [],
        tolerance: 5.0,
        delay: 0.5,
        next_if_true: 'end',
        next_if_false: 'end'
      };
    }
    setNodes([...nodes, newNode]);
  };

  const updateNode = (index, field, value) => {
    const updated = [...nodes];
    updated[index][field] = value;
    setNodes(updated);
  };

  const removeNode = (index) => {
    const updated = [...nodes];
    updated.splice(index, 1);
    setNodes(updated);
  };

  const captureCoord = async (index) => {
    setIsWaiting(true);
    try {
      const res = await fetch(`${API_BASE}/capture_coord`);
      if (res.ok) {
        const data = await res.json();
        updateNode(index, 'x', data.x);
        updateNode(index, 'y', data.y);
      }
    } catch (e) {
      console.error(e);
    }
    setIsWaiting(false);
  };

  const captureRegion = async (index) => {
    setIsWaiting(true);
    try {
      const res = await fetch(`${API_BASE}/capture_region`);
      if (res.ok) {
        const data = await res.json();
        const updated = [...nodes];
        updated[index].bbox = data.bbox;
        updated[index].baseline = data.baseline;
        setNodes(updated);
      }
    } catch (e) {
      console.error(e);
    }
    setIsWaiting(false);
  };

  const groupedNodes = nodes.reduce((acc, node, index) => {
    const loopId = node.loopId || 'Loop_1';
    if (!acc[loopId]) acc[loopId] = [];
    acc[loopId].push({ node, index });
    return acc;
  }, {});

  const nodeIds = ['end', ...nodes.map(n => n.id)];

  return (
    <div className="layout-grid">
      <div className="left-panel">

        <div className="pixel-box">
          <h2>💾 Macro Storage</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div className="property-group">
              <label>NAME:</label>
              <input type="text" value={saveFilename} onChange={e => setSaveFilename(e.target.value)} style={{ width: '120px' }} />
              <button className="action-btn" onClick={handleSaveFile}>[ SAVE ]</button>
            </div>
            <div style={{ width: '100%', margin: '5px 0', borderTop: '2px dashed #888' }}></div>
            <div className="property-group">
              <label>LOAD:</label>
              <select value={selectedScript} onChange={e => setSelectedScript(e.target.value)} style={{ width: '120px' }}>
                {scriptList.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
              <button onClick={handleLoadFile} style={{ backgroundColor: '#F8D820' }}>[ LOAD ]</button>
            </div>
          </div>
        </div>

        <div className="pixel-box">
          <h2>Control Panel</h2>

          <div style={{ marginBottom: '15px', padding: '10px', border: '2px dashed #C84C0C', backgroundColor: '#FFFDE7', color: '#000' }}>
            <strong>🛡️ ANTI-BAN BREAK</strong>
            <div className="property-group" style={{ marginTop: '5px' }}>
              <label>Rest Every (min):</label>
              <input type="number" step="0.5" value={restInterval} onChange={e => setRestInterval(e.target.value)} style={{ width: '80px' }} />
            </div>
            <div className="property-group">
              <label>Rest For (sec):</label>
              <input type="number" value={restDuration} onChange={e => setRestDuration(e.target.value)} style={{ width: '80px' }} />
            </div>
            <div className="property-group" style={{ marginTop: '5px' }}>
              <label>Extra Steps b/f Stop:</label>
              <input type="number" value={stopDelaySteps} onChange={e => setStopDelaySteps(e.target.value)} style={{ width: '80px' }} />
            </div>
            <small>(Set to 0 to disable)</small>
          </div>

          <div style={{ marginBottom: '15px', padding: '10px', border: '2px solid #0088cc', backgroundColor: '#e6f7ff', color: '#000' }}>
            <strong>📱 TELEGRAM BOT</strong>
            <div className="property-group" style={{ marginTop: '5px' }}>
              <label>Bot Token:</label>
              <input type="text" value={botToken} onChange={e => setBotToken(e.target.value)} style={{ width: '150px' }} />
            </div>
            <div className="property-group">
              <label>Chat ID:</label>
              <input type="text" value={chatId} onChange={e => setChatId(e.target.value)} style={{ width: '150px' }} />
            </div>
            <button className="action-btn" onClick={handleSaveTelegram} style={{ marginTop: '5px', backgroundColor: '#0088cc', color: '#fff', padding: '5px 10px' }}>[ SAVE TELEGRAM ]</button>
            <br />
            <small style={{display: 'block', marginTop: '5px'}}>Send /start to your bot to get your Chat ID.</small>
          </div>

          <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
            <button onClick={handleStart} disabled={isWaiting}>[ START ]</button>
            <button className="danger" onClick={handleStop} disabled={isWaiting}>[ STOP ]</button>
          </div>
          <p>STATUS: <span style={{ color: status.is_running ? '#00A800' : '#E40058' }}>
            {status.is_running ? 'RUNNING' : 'IDLE'}
          </span></p>
          <p>ACTIVE STEP: {status.current_step || 'NONE'}</p>
        </div>

        <div className="pixel-box">
          <h2>Terminal Log</h2>
          <div className="terminal-container" ref={terminalRef} style={{ color: '#39FF14' }}>
            {serverLogs.map((l, i) => <div key={i} className="terminal-line" style={{ color: '#39FF14' }}>{l}</div>)}
            <div className="terminal-line"><span className="cursor" style={{ color: '#39FF14' }}>_</span></div>
          </div>
        </div>
      </div>

      <div className="right-panel">
        <div className="pixel-box">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h2 style={{ margin: 0, border: 'none' }}>Sequence Builder</h2>
            <button style={{ borderColor: '#000' }} onClick={handleDeploy}>DEPLOY SCRIPT</button>
          </div>

          <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
            <button onClick={() => addNode('click')}>+ CLICK</button>
            <button onClick={() => addNode('wait')}>+ WAIT</button>
            <button className="retro-btn bg-coin-yellow" onClick={() => addNode('keypress')}>[ ⌨️ + KEYPRESS ]</button>
            <button onClick={() => addNode('check_image')}>+ CHECK IMAGE</button>
          </div>

          <div className="nodes-container">
            {Object.keys(groupedNodes).map((loopId) => (
              <div key={loopId} className="loop-group" style={{ border: '4px solid #C84C0C', padding: '10px', marginBottom: '20px', backgroundColor: '#FFFDE7', boxShadow: '4px 4px 0px #000' }}>
                <h3 style={{ marginTop: 0, color: '#000', textTransform: 'uppercase' }}>Group: {loopId}</h3>

                {groupedNodes[loopId].map(({ node, index: i }) => (
                  <div key={i} className="node-card">
                    <div className="node-header">
                      <span>{node.id} [{node.type.toUpperCase()}]</span>
                      <button className="danger" onClick={() => removeNode(i)}>X</button>
                    </div>

                    <div className="node-properties">
                      <div className="property-group"><label>LOOP_ID:</label> <input type="text" value={node.loopId || 'Loop_1'} onChange={e => updateNode(i, 'loopId', e.target.value)} /></div>
                      <div style={{ width: '100%', margin: '2px 0', borderTop: '2px dashed #888' }}></div>

                      {node.type === 'click' && (
                        <>
                          <div className="property-group"><label>X:</label> <input type="number" value={node.x} onChange={e => updateNode(i, 'x', parseInt(e.target.value) || 0)} /></div>
                          <div className="property-group"><label>Y:</label> <input type="number" value={node.y} onChange={e => updateNode(i, 'y', parseInt(e.target.value) || 0)} /></div>
                          <button className="action-btn" onClick={() => captureCoord(i)} disabled={isWaiting}>[ 🎯 CLICK TO CAPTURE ]</button>
                          <div className="property-group"><label>DELAY(s):</label> <input type="number" step="0.1" value={node.delay} onChange={e => updateNode(i, 'delay', parseFloat(e.target.value) || 0)} /></div>
                          <div className="property-group">
                            <label>NEXT_ID:</label>
                            <select value={node.next} onChange={e => updateNode(i, 'next', e.target.value)}>
                              {nodeIds.map(id => <option key={id} value={id}>{id}</option>)}
                            </select>
                          </div>
                        </>
                      )}

                      {node.type === 'keypress' && (
                        <>
                          <div className="property-group">
                            <label>KEY:</label>
                            <select value={node.key} onChange={e => updateNode(i, 'key', e.target.value)}>
                              <option value="enter">enter</option>
                              <option value="esc">esc</option>
                              <option value="space">space</option>
                              <option value="up">up</option>
                              <option value="down">down</option>
                              <option value="left">left</option>
                              <option value="right">right</option>
                              <option value="tab">tab</option>
                            </select>
                          </div>
                          <div className="property-group"><label>DELAY(s):</label> <input type="number" step="0.1" value={node.delay} onChange={e => updateNode(i, 'delay', parseFloat(e.target.value) || 0)} /></div>
                          <div className="property-group">
                            <label>NEXT_ID:</label>
                            <select value={node.next} onChange={e => updateNode(i, 'next', e.target.value)}>
                              {nodeIds.map(id => <option key={id} value={id}>{id}</option>)}
                            </select>
                          </div>
                        </>
                      )}

                      {node.type === 'check_image' && (
                        <>
                          <div className="property-group"><label>TOLERANCE(%):</label> <input type="number" step="0.1" value={node.tolerance} onChange={e => updateNode(i, 'tolerance', parseFloat(e.target.value) || 0)} /></div>
                          <div className="property-group"><label>DELAY(s):</label> <input type="number" step="0.1" value={node.delay} onChange={e => updateNode(i, 'delay', parseFloat(e.target.value) || 0)} /></div>
                          <div className="property-group">
                            <label>IF_TRUE:</label>
                            <select value={node.next_if_true} onChange={e => updateNode(i, 'next_if_true', e.target.value)}>
                              {nodeIds.map(id => <option key={id} value={id}>{id}</option>)}
                            </select>
                          </div>
                          <div className="property-group">
                            <label>IF_FALSE:</label>
                            <select value={node.next_if_false} onChange={e => updateNode(i, 'next_if_false', e.target.value)}>
                              {nodeIds.map(id => <option key={id} value={id}>{id}</option>)}
                            </select>
                          </div>
                          <div style={{ width: '100%', margin: '5px 0', borderTop: '2px dashed #888' }}></div>
                          <button className="action-btn" onClick={() => captureRegion(i)} disabled={isWaiting}>[ ✂️ SNIP REGION ]</button>
                          {node.bbox && (
                            <span style={{ fontSize: '1rem', fontWeight: 'bold' }}>
                              BBOX: L={node.bbox.left} T={node.bbox.top} W={node.bbox.width} H={node.bbox.height}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
