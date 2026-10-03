import {Component, type ReactNode, type ErrorInfo} from 'react';

export class RenderBoundary extends Component<{
  children:ReactNode;
  view?:boolean;
  onClose?:()=>void;
}, {failed:boolean}> {
  state={failed:false};
  static getDerivedStateFromError(){return {failed:true};}
  componentDidCatch(error:Error,info:ErrorInfo){
    // Keep details in the developer console, never replace the whole screen.
    console.error('Workbench render failed',error,info.componentStack);
  }
  render(){
    if(!this.state.failed) return this.props.children;
    return <div className="render-recovery" role="alert">
      <strong>{this.props.view?'视图未能显示':'工作台未能显示'}</strong>
      <div>
        <button onClick={()=>this.setState({failed:false})}>重试此视图</button>
        {this.props.onClose?<button onClick={this.props.onClose}>关闭此视图</button>:<button onClick={()=>location.reload()}>重新加载工作台</button>}
      </div>
    </div>;
  }
}
