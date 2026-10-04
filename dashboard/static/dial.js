// Static instrument: seven rings encode actual frozen-file hash coverage.
// Draw only on resize/theme/data changes; no animation loop or simulated signal.
export function drawIntegrity(canvas,matching,total) {
  const draw=()=>{
    if(document.hidden||!canvas.isConnected)return;
    const size=canvas.getBoundingClientRect().width;if(!size)return;
    const ratio=Math.min(devicePixelRatio||1,2);canvas.width=size*ratio;canvas.height=size*ratio;
    const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);ctx.clearRect(0,0,size,size);
    const styles=getComputedStyle(document.documentElement),ink=styles.getPropertyValue('--ink-rgb').trim();
    const ember=styles.getPropertyValue('--ember').trim(),fraction=total?matching/total:0,center=size/2;
    const minimum=size*.265,step=size*.024;
    for(let ring=0;ring<7;ring++){
      const radius=minimum+ring*step,count=Math.floor(2*Math.PI*radius/(size*.02));
      for(let dot=0;dot<count;dot++){
        const angle=dot/count*Math.PI*2-Math.PI/2;
        ctx.beginPath();ctx.arc(center+Math.cos(angle)*radius,center+Math.sin(angle)*radius,size*.00265,0,Math.PI*2);
        ctx.fillStyle=`rgb(${ink} / ${dot/count < fraction ? .72 : .13})`;ctx.fill();
      }
    }
    const outer=size*.455;
    ctx.beginPath();ctx.arc(center,center,outer,0,Math.PI*2);ctx.strokeStyle=`rgb(${ink} / .15)`;ctx.lineWidth=.6;ctx.stroke();
    for(let tick=0;tick<60;tick++){
      const angle=tick/60*Math.PI*2-Math.PI/2,long=tick%5===0;
      ctx.beginPath();ctx.moveTo(center+Math.cos(angle)*outer,center+Math.sin(angle)*outer);
      ctx.lineTo(center+Math.cos(angle)*(outer+(long?7:3)),center+Math.sin(angle)*(outer+(long?7:3)));
      ctx.strokeStyle=`rgb(${ink} / ${long ? .4 : .18})`;ctx.stroke();
    }
    if(total&&matching<total){
      const angle=fraction*Math.PI*2-Math.PI/2;
      ctx.beginPath();ctx.arc(center+Math.cos(angle)*(minimum+step*6),center+Math.sin(angle)*(minimum+step*6),2,0,Math.PI*2);ctx.fillStyle=ember;ctx.fill();
    }
  };
  draw();new ResizeObserver(draw).observe(canvas);matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
  document.addEventListener('visibilitychange',draw);
}
