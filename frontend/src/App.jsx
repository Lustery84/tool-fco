import React, { useState, useEffect, useRef } from 'react';

const API_BASE = 'http://localhost:8000';

function App() {
  const [nodes, setNodes] = useState([
    { id: 'step_1', type: 'click', x: 100, y: 200, delay: 1.0, next: 'end' }
  ]);
  const [status, setStatus] = useState({ is_running: false, current_step: null });
  const [logs, setLogs] = useState(["System initialized..."]);
  
  const terminalRef = useRef(null);

  const addLog = (msg) => {
    setLogs(prev => [...prev.slice(-49), `${new Date().toLocaleTimeString()} - ${msg}`]);
  };

  // Auto-scroll terminal
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logs]);

  // Polling backend status
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/status`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data);
        }
      } catch (err) {
        // Silent fail if server is down
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const handleStart = async () => {
    try {
      const res = await fetch(`${API_BASE}/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_step: 'step_1' })
      });
      const data = await res.json();
      addLog(data.detail || data.message || 'START command sent.');
    } catch (e) {
      addLog(`ERR: ${e.message}`);
    }
  };

  const handleStop = async () => {
    try {
      const res = await fetch(`${API_BASE}/stop`, { method: 'POST' });
      const data = await res.json();
      addLog(data.message || 'STOP command sent.');
    } catch (e) {
      addLog(`ERR: ${e.message}`);
    }
  };

  const handleDeploy = async () => {
    const script = {};
    nodes.forEach(n => {
      const { id, type, ...rest } = n;
      script[id] = { type, ...rest };
    });
    
    try {
      const res = await fetch(`${API_BASE}/load_script`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script })
      });
      const data = await res.json();
      addLog(`SCRIPT DEPLOYED: ${data.total_steps || 0} nodes sent.`);
    } catch (e) {
      addLog(`ERR Deploying: ${e.message}`);
    }
  };

  const addNode = (type) => {
    const id = `step_${nodes.length + 1}`;
    let newNode = { id, type };
    if (type === 'click') {
      newNode = { ...newNode, x: 0, y: 0, delay: 1.0, next: 'end' };
    } else if (type === 'wait') {
      // Treating 'wait' as a click node with 0,0 coords and a delay under the hood
      newNode = { ...newNode, type: 'click', x: 0, y: 0, delay: 5.0, next: 'end' };
    } else if (type === 'check_image') {
      newNode = { 
        ...newNode, 
        bbox: { left: 0, top: 0, width: 100, height: 100 }, 
        baseline: [], // Mocking empty baseline array for now
        tolerance: 5.0, 
        next_if_true: 'end', 
        next_if_false: 'end' 
      };
    }
    setNodes([...nodes, newNode]);
    addLog(`Added new node: ${id} [${type.toUpperCase()}]`);
  };

  const updateNode = (index, field, value) => {
    const updated = [...nodes];
    updated[index][field] = value;
    setNodes(updated);
  };
  
  const updateNodeNested = (index, parent, field, value) => {
    const updated = [...nodes];
    updated[index][parent] = { ...updated[index][parent], [field]: value };
    setNodes(updated);
  };

  const removeNode = (index) => {
    const updated = [...nodes];
    addLog(`Removed node: ${updated[index].id}`);
    updated.splice(index, 1);
    setNodes(updated);
  };

  return (
     <div className="layout-grid">
       <div className="left-panel">
         <div className="pixel-box">
           <h2>Control Panel</h2>
           <div style={{ display: 'flex', gap: '10px', marginBottom: '15px' }}>
             <button onClick={handleStart}>[ START ]</button>
             <button className="danger" onClick={handleStop}>[ STOP ]</button>
           </div>
           <p>STATUS: <span style={{ color: status.is_running ? '#39ff14' : '#ff0000' }}>
             {status.is_running ? 'RUNNING' : 'IDLE'}
           </span></p>
           <p>ACTIVE STEP: {status.current_step || 'NONE'}</p>
         </div>
         
         <div className="pixel-box">
           <h2>Terminal Log</h2>
           <div className="terminal-container" ref={terminalRef}>
             {logs.map((l, i) => <div key={i} className="terminal-line">{l}</div>)}
             <div className="terminal-line"><span className="cursor">_</span></div>
           </div>
         </div>
       </div>

       <div className="right-panel">
         <div className="pixel-box">
           <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
             <h2 style={{ margin: 0, border: 'none' }}>Sequence Builder</h2>
             <button style={{ borderColor: '#fff' }} onClick={handleDeploy}>DEPLOY SCRIPT</button>
           </div>
           
           <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
             <button onClick={() => addNode('click')}>+ CLICK</button>
             <button onClick={() => addNode('wait')}>+ WAIT</button>
             <button onClick={() => addNode('check_image')}>+ CHECK IMAGE</button>
           </div>

           <div className="nodes-container">
             {nodes.map((node, i) => (
               <div key={i} className="node-card">
                 <div className="node-header">
                   <span>{node.id} [{node.type.toUpperCase()}]</span>
                   <button className="danger" onClick={() => removeNode(i)}>X</button>
                 </div>
                 
                 <div className="node-properties">
                   {/* Click Node & Wait Node (Mocked as click) */}
                   {node.type === 'click' && (
                     <>
                       <div className="property-group"><label>X:</label> <input type="number" value={node.x} onChange={e => updateNode(i, 'x', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>Y:</label> <input type="number" value={node.y} onChange={e => updateNode(i, 'y', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>DELAY(s):</label> <input type="number" step="0.1" value={node.delay} onChange={e => updateNode(i, 'delay', parseFloat(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>NEXT_ID:</label> <input type="text" value={node.next} onChange={e => updateNode(i, 'next', e.target.value)} /></div>
                     </>
                   )}
                   {/* Check Image Node */}
                   {node.type === 'check_image' && (
                     <>
                       <div className="property-group"><label>TOLERANCE(%):</label> <input type="number" step="0.1" value={node.tolerance} onChange={e => updateNode(i, 'tolerance', parseFloat(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>IF_TRUE:</label> <input type="text" value={node.next_if_true} onChange={e => updateNode(i, 'next_if_true', e.target.value)} /></div>
                       <div className="property-group"><label>IF_FALSE:</label> <input type="text" value={node.next_if_false} onChange={e => updateNode(i, 'next_if_false', e.target.value)} /></div>
                       <div style={{ width: '100%', margin: '5px 0', borderTop: '1px dashed #39ff14' }}></div>
                       <div className="property-group"><label>BBOX L:</label> <input type="number" value={node.bbox.left} onChange={e => updateNodeNested(i, 'bbox', 'left', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>BBOX T:</label> <input type="number" value={node.bbox.top} onChange={e => updateNodeNested(i, 'bbox', 'top', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>BBOX W:</label> <input type="number" value={node.bbox.width} onChange={e => updateNodeNested(i, 'bbox', 'width', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group"><label>BBOX H:</label> <input type="number" value={node.bbox.height} onChange={e => updateNodeNested(i, 'bbox', 'height', parseInt(e.target.value) || 0)} /></div>
                       <div className="property-group" style={{ width: '100%' }}><small>(Note: `baseline` array generation must be wired up programmatically to capture a reference image snippet)</small></div>
                     </>
                   )}
                 </div>
               </div>
             ))}
           </div>
         </div>
       </div>
     </div>
  );
}

export default App;
