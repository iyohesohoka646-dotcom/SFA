import type {Explanation,OperationRecord,ValueDescriptor} from './generated';
export function explainOperation(operation:OperationRecord,descriptors:ValueDescriptor[]):Explanation{
  const label=operation.label;let text='执行此源码表达式，记录实际输入与输出。其数学含义尚未识别。';
  const axis=label.match(/mean\([^)]*axis\s*=\s*(\d+)/);
  if(axis)text=`沿 axis=${axis[1]} 求均值，聚合该维度。`;
  else if(/\([^)]*-[^)]*\)\s*\//.test(label))text='先减去中心值，再除以尺度；这是标准化形式。尺度为零或数据缺失可能产生非有限值。';
  else if(/std\(/.test(label))text='计算标准差，刻画数值的离散程度。';
  else if(/\.linalg\.eigh\(/.test(label))text='计算厄米矩阵的特征值与特征向量；对称性和数值质量由探针另行验证。';
  else if(/@|\.dot\(|matmul\(/.test(label))text='执行矩阵乘法，按实际输入与输出形状检查相邻维度。';
  else if(/\.T\b|transpose\(/.test(label))text='转置数据的轴，输出形状以运行记录为准。';
  else if(/reshape\(/.test(label))text='重新组织数据形状；是否共享底层存储以描述符为准。';
  else if(/zeros\(|ones\(|arange\(|normal\(/.test(label))text='定义一个数组，实际形状、dtype 与来源见此变量记录。';
  else if(/\[[^\]]*:[^\]]*\]/.test(label))text='选择数组的一部分；观察值对应这次执行的具体版本。';
  return {operation_id:operation.id,text,origin:'rule',evidence:[operation.id,...operation.input_snapshots,...operation.output_snapshots],
    uncertainty:[...(!descriptors.every(d=>d.axes.length)?['轴的实验语义未标注']:[]),...(!descriptors.every(d=>d.unit)?['单位未标注']:[])],usage:{},sent_scope:{requests:0,source:'local rule'}};
}
